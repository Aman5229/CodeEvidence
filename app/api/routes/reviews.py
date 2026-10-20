from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.errors import error_responses
from app.db.models import PullRequest, Repository, Review, ReviewFinding
from app.db.session import get_db
from app.jobs import enqueue_job, index_repository, review_pull_request
from app.modules.review.feedback import record_feedback
from app.schemas.jobs import IndexRepositoryPayload, ReviewPullRequestPayload
from app.schemas.review import (
  EvidenceOut,
  FeedbackCounts,
  FeedbackIn,
  FeedbackOut,
  FindingOut,
  QueuedJobOut,
  ReviewOut,
  ReviewRunOut,
)

router = APIRouter(tags=["reviews"])


@router.get(
  "/pull-requests/{pull_request_id}/review",
  response_model=ReviewOut,
  responses=error_responses(404, 422),
)
def get_review(pull_request_id: int, db: Session = Depends(get_db)):
  """
  The PR's latest AI review: a short summary and the findings that passed verification,
  best first, each with the evidence it cites and the feedback it received. Queue a review
  with POST on the same path.
  """
  review = db.scalars(
    select(Review)
    .where(Review.pull_request_id == pull_request_id)
    .order_by(Review.created_at.desc(), Review.id.desc())
    .options(selectinload(Review.findings).selectinload(ReviewFinding.feedback))
    .limit(1)
  ).first()
  if review is None:
    if db.get(PullRequest, pull_request_id) is None:
      raise HTTPException(status_code=404, detail="Pull request not found")
    raise HTTPException(status_code=404, detail="No review yet: queue one with POST /pull-requests/{id}/review")

  evidence = {item["id"]: EvidenceOut(**item) for item in review.evidence}
  shown = sorted((f for f in review.findings if f.rank is not None), key=lambda f: f.rank)
  findings = []
  for finding in shown:
    verdicts = Counter(feedback.verdict for feedback in finding.feedback)
    findings.append(
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
        confidence=finding.confidence,
        evidence=[evidence[item_id] for item_id in finding.evidence if item_id in evidence],
        feedback=FeedbackCounts(
          useful=verdicts["useful"],
          not_useful=verdicts["not_useful"],
          replies=sum(feedback.source == "github_reply" for feedback in finding.feedback),
        ),
        github_comment_id=finding.github_comment_id,
      )
    )
  return ReviewOut(
    id=review.id,
    pull_request_id=review.pull_request_id,
    head_sha=review.head_sha,
    status=review.status,
    summary=review.summary,
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
    published_at=review.published_at,
    created_at=review.created_at,
  )


@router.get(
  "/pull-requests/{pull_request_id}/reviews",
  response_model=list[ReviewRunOut],
  responses=error_responses(404, 422),
)
def list_reviews(pull_request_id: int, db: Session = Depends(get_db)):
  """Every review run of the PR, newest first: model, prompt, cost and how many findings
  were shown or dropped. The findings of the latest run come from GET .../review."""
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
def queue_review(pull_request_id: int, db: Session = Depends(get_db)):
  """Queue an AI review of the PR. An identical earlier review is reused at no cost."""
  if db.get(PullRequest, pull_request_id) is None:
    raise HTTPException(status_code=404, detail="Pull request not found")
  try:
    job = enqueue_job(db, review_pull_request, ReviewPullRequestPayload(pull_request_id=pull_request_id), event_id=None)
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
  """Rate a finding from the dashboard: useful or not useful."""
  finding = db.get(ReviewFinding, finding_id)
  if finding is None:
    raise HTTPException(status_code=404, detail="Finding not found")
  saved = record_feedback(db, finding, source="dashboard", verdict=feedback.verdict)
  db.commit()
  return FeedbackOut(id=saved.id, finding_id=finding.id, verdict=saved.verdict, created_at=saved.created_at)
