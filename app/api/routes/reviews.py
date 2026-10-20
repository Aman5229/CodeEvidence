import logging
from collections import Counter, defaultdict
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.errors import error_responses
from app.db.models import FindingFeedback, PullRequest, Repository, Review, ReviewFinding
from app.db.session import get_db
from app.jobs import distill_learning, enqueue_job, index_repository, review_pull_request
from app.modules.review.feedback import record_feedback
from app.modules.review.fixes import agent_prompt
from app.modules.triage import pull_request_effort
from app.schemas.jobs import DistillLearningPayload, IndexRepositoryPayload, ReviewPullRequestPayload
from app.schemas.repo_config import RepoConfigOut
from app.schemas.review import (
  EvidenceOut,
  FeedbackCounts,
  FeedbackIn,
  FeedbackOut,
  FindingOut,
  QueuedJobOut,
  ReviewOut,
  ReviewRunOut,
  ToolRunOut,
)
from app.schemas.triage import EffortOut

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reviews"])


def feedback_by_key(db: Session, pull_request_id: int, keys: list[str]) -> dict[str, FeedbackCounts]:
  """Feedback per problem (finding key) across all reviews of the PR: a 👎 given on an earlier
  review still shows when a later review finds the same problem, or carries it over."""
  counts: dict[str, Counter] = defaultdict(Counter)
  for key, verdict, source in db.execute(
    select(ReviewFinding.finding_key, FindingFeedback.verdict, FindingFeedback.source)
    .join(FindingFeedback, FindingFeedback.finding_id == ReviewFinding.id)
    .join(Review, Review.id == ReviewFinding.review_id)
    .where(Review.pull_request_id == pull_request_id, ReviewFinding.finding_key.in_(keys))
  ):
    counts[key][verdict] += 1
    counts[key]["replies"] += source == "github_reply"
  return {
    key: FeedbackCounts(useful=count["useful"], not_useful=count["not_useful"], replies=count["replies"])
    for key, count in counts.items()
  }


@router.get(
  "/pull-requests/{pull_request_id}/review",
  response_model=ReviewOut,
  responses=error_responses(404, 422),
)
def get_review(pull_request_id: int, db: Session = Depends(get_db)):
  """
  The PR's latest AI review: a short summary, a diagram of the change, the estimated review
  effort, and the findings that passed verification, best first, each with the evidence it
  cites, a one-click fix when there is one, and the feedback it received. Queue a review
  with POST on the same path.
  """
  review = db.scalars(
    select(Review)
    .where(Review.pull_request_id == pull_request_id)
    .order_by(Review.created_at.desc(), Review.id.desc())
    .options(selectinload(Review.findings))
    .limit(1)
  ).first()
  if review is None:
    if db.get(PullRequest, pull_request_id) is None:
      raise HTTPException(status_code=404, detail="Pull request not found")
    raise HTTPException(status_code=404, detail="No review yet: queue one with POST /pull-requests/{id}/review")
  pull_request = db.get(PullRequest, review.pull_request_id)
  repository = db.get(Repository, pull_request.repository_id)

  evidence = {item["id"]: EvidenceOut(**item) for item in review.evidence}
  shown = sorted((f for f in review.findings if f.rank is not None), key=lambda f: f.rank)
  feedback = feedback_by_key(db, pull_request.id, [finding.finding_key for finding in shown])
  findings = [
    FindingOut(
      id=finding.id,
      rank=finding.rank,
      path=finding.path,
      line=finding.line,
      severity=finding.severity,
      category=finding.category,
      claim=finding.claim,
      quote=finding.quote,
      suggestion=finding.suggestion,
      replacement=finding.replacement,
      original_line=finding.original_line,
      agent_prompt=agent_prompt(
        path=finding.path, line=finding.line, claim=finding.claim, quote=finding.quote,
        suggestion=finding.suggestion, replacement=finding.replacement,
      ),
      confidence=finding.confidence,
      evidence=[evidence[item_id] for item_id in finding.evidence if item_id in evidence],
      feedback=feedback.get(finding.finding_key, FeedbackCounts(useful=0, not_useful=0, replies=0)),
      github_comment_id=finding.github_comment_id,
      carried_from_review_id=finding.carried_from_review_id,
    )
    for finding in shown
  ]
  return ReviewOut(
    id=review.id,
    pull_request_id=review.pull_request_id,
    pull_request_url=f"{repository.html_url}/pull/{pull_request.number}",
    head_sha=review.head_sha,
    status=review.status,
    mode=review.mode,
    base_review_id=review.base_review_id,
    compared_from_sha=review.compared_from_sha,
    summary=review.summary,
    diagram=review.diagram,
    effort=EffortOut(**asdict(pull_request_effort(db, pull_request.id))),
    findings=findings,
    dropped_findings=sum(finding.status == "dropped" for finding in review.findings),
    evidence=list(evidence.values()),
    prompt_version=review.prompt_version,
    model=review.model,
    cached=review.cached,
    llm_calls=review.llm_calls,
    input_tokens=review.input_tokens,
    output_tokens=review.output_tokens,
    cost_usd=review.cost_usd,
    latency_ms=review.latency_ms,
    tools=[ToolRunOut(**run) for run in review.tools] if review.tools is not None else None,
    config=RepoConfigOut.model_validate(review.config) if review.config else None,
    check_state=review.check_state,
    published_at=review.published_at,
    created_at=review.created_at,
  )


@router.get(
  "/pull-requests/{pull_request_id}/reviews",
  response_model=list[ReviewRunOut],
  responses=error_responses(404, 422),
)
def list_reviews(pull_request_id: int, db: Session = Depends(get_db)):
  """Every review run of the PR, newest first: full or incremental, model, prompt, cost and
  how many findings were shown or dropped. The findings of the latest run come from
  GET .../review."""
  if db.get(PullRequest, pull_request_id) is None:
    raise HTTPException(status_code=404, detail="Pull request not found")
  shown = func.count(ReviewFinding.id).filter(ReviewFinding.rank.is_not(None))
  dropped = func.count(ReviewFinding.id).filter(ReviewFinding.status == "dropped")
  rows = db.execute(
    select(Review, shown, dropped)
    .outerjoin(ReviewFinding, ReviewFinding.review_id == Review.id)
    .where(Review.pull_request_id == pull_request_id)
    .group_by(Review.id)
    .order_by(Review.created_at.desc(), Review.id.desc())
  ).all()
  return [
    ReviewRunOut(
      id=review.id,
      status=review.status,
      mode=review.mode,
      base_review_id=review.base_review_id,
      model=review.model,
      prompt_version=review.prompt_version,
      cached=review.cached,
      llm_calls=review.llm_calls,
      input_tokens=review.input_tokens,
      output_tokens=review.output_tokens,
      cost_usd=review.cost_usd,
      latency_ms=review.latency_ms,
      findings_shown=shown_count,
      findings_dropped=dropped_count,
      check_state=review.check_state,
      published_at=review.published_at,
      created_at=review.created_at,
    )
    for review, shown_count, dropped_count in rows
  ]


@router.post(
  "/pull-requests/{pull_request_id}/review",
  status_code=202,
  response_model=QueuedJobOut,
  responses=error_responses(404, 422, 503),
)
def queue_review(pull_request_id: int, mode: Literal["auto", "full"] = "auto", db: Session = Depends(get_db)):
  """Queue an AI review of the PR. `mode=auto`: when the PR got new commits on top of its last
  review, only the files changed since are reviewed and the other findings are carried over
  (incremental); otherwise everything is. `mode=full`: always everything. An identical
  earlier review is reused at no cost."""
  if db.get(PullRequest, pull_request_id) is None:
    raise HTTPException(status_code=404, detail="Pull request not found")
  payload = ReviewPullRequestPayload(pull_request_id=pull_request_id, mode=mode)
  try:
    job = enqueue_job(db, review_pull_request, payload, event_id=None)
  except Exception as error:
    raise HTTPException(status_code=503, detail="Could not queue the review") from error
  return QueuedJobOut(job_id=job.id, status=job.status)


@router.post(
  "/repositories/{repository_id}/index",
  status_code=202,
  response_model=QueuedJobOut,
  responses=error_responses(404, 422, 503),
  tags=["repositories"],
)
def queue_index(repository_id: int, db: Session = Depends(get_db)):
  """Queue indexing of the repository's code for retrieval. Re-runs only redo changed files."""
  if db.get(Repository, repository_id) is None:
    raise HTTPException(status_code=404, detail="Repository not found")
  try:
    job = enqueue_job(db, index_repository, IndexRepositoryPayload(repository_id=repository_id), event_id=None)
  except Exception as error:
    raise HTTPException(status_code=503, detail="Could not queue indexing") from error
  return QueuedJobOut(job_id=job.id, status=job.status)


@router.post(
  "/findings/{finding_id}/feedback",
  status_code=201,
  response_model=FeedbackOut,
  responses=error_responses(404, 422),
)
def add_feedback(finding_id: int, feedback: FeedbackIn, db: Session = Depends(get_db)):
  """Rate a finding from the dashboard: useful or not useful. A reason given with "not useful"
  is turned into a learning (a job), so future reviews of the repository avoid the mistake."""
  finding = db.get(ReviewFinding, finding_id)
  if finding is None:
    raise HTTPException(status_code=404, detail="Finding not found")
  reason = (feedback.reason or "").strip() or None
  saved = record_feedback(db, finding, source="dashboard", verdict=feedback.verdict, body=reason)
  db.commit()
  learning_job_id = None
  if feedback.verdict == "not_useful" and reason:
    payload = DistillLearningPayload(finding_id=finding.id, reason=reason, source="dashboard")
    try:
      learning_job_id = enqueue_job(db, distill_learning, payload, event_id=None).id
    except Exception:  # the feedback is saved; the failed job is visible in the jobs list
      logger.warning("Could not queue the learning job for finding %s", finding.id, exc_info=True)
  return FeedbackOut(
    id=saved.id, finding_id=finding.id, verdict=saved.verdict, created_at=saved.created_at,
    learning_job_id=learning_job_id,
  )
