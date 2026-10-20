from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from typing import Any, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.core.time_utils import utc_now
from app.db.models import PullRequest, PullRequestFile, PullRequestRisk, Repository, Review, ReviewFinding
from app.db.session import get_db
from app.modules.triage import Effort, Priority, effort_of_files, prioritize, suggest_reviewers
from app.schemas.triage import EffortOut, QueueItemOut, ReviewerOut, ReviewQueueOut

router = APIRouter(tags=["triage"])


class Ranked(NamedTuple):
  priority: Priority
  pull_request: PullRequest
  repository: str
  risk: PullRequestRisk | None
  effort: Effort
  review: Any  # the latest review's row (id, status), or None
  shown: int
  high: int
  waiting: float  # hours
  created_at: datetime


@router.get("/review-queue", response_model=ReviewQueueOut, responses=error_responses(404, 422))
def review_queue(
  repository_id: int | None = None,
  limit: int = Query(default=50, ge=1, le=200),
  db: Session = Depends(get_db),
):
  """
  Open PRs in the order to review them, highest priority first, each with its band (P1
  review first, P2, P3), the reasons, an estimated review time and the people who changed
  the same files before (suggested reviewers). The totals cover every open PR; `items` holds
  the first `limit`.

  Priority mixes the risk score, the model's prediction, how long the PR has waited, and a
  small boost for quick reviews; high-severity findings add to it.
  """
  if repository_id is not None and db.get(Repository, repository_id) is None:
    raise HTTPException(status_code=404, detail="Repository not found")
  query = (
    select(PullRequest, Repository.full_name, PullRequestRisk)
    .join(Repository, Repository.id == PullRequest.repository_id)
    .outerjoin(PullRequestRisk, PullRequestRisk.pull_request_id == PullRequest.id)
    .where(PullRequest.status == "open")
  )
  if repository_id is not None:
    query = query.where(PullRequest.repository_id == repository_id)
  rows = db.execute(query).all()
  ids = [pull_request.id for pull_request, _, _ in rows]

  files: dict[int, list[tuple[str, int, int]]] = defaultdict(list)
  for pull_request_id, path, additions, deletions in db.execute(
    select(PullRequestFile.pull_request_id, PullRequestFile.path, PullRequestFile.additions, PullRequestFile.deletions)
    .where(PullRequestFile.pull_request_id.in_(ids))
  ):
    files[pull_request_id].append((path, additions, deletions))
  latest = {
    row.pull_request_id: row
    for row in db.execute(
      select(Review.id, Review.pull_request_id, Review.status)
      .where(Review.pull_request_id.in_(ids))
      .order_by(Review.pull_request_id, Review.created_at.desc(), Review.id.desc())
      .ext(distinct_on(Review.pull_request_id))  # Postgres DISTINCT ON: the newest review of each PR
    )
  }
  counts = {
    review_id: (shown, high)
    for review_id, shown, high in db.execute(
      select(ReviewFinding.review_id, func.count(), func.count().filter(ReviewFinding.severity == "high"))
      .where(ReviewFinding.review_id.in_([row.id for row in latest.values()]), ReviewFinding.rank.is_not(None))
      .group_by(ReviewFinding.review_id)
    )
  }

  now = utc_now()
  ranked = []
  for pull_request, repository, risk in rows:
    effort = effort_of_files(files[pull_request.id])
    review = latest.get(pull_request.id)
    shown, high = counts.get(review.id, (0, 0)) if review else (0, 0)
    waiting = max(0.0, (now - pull_request.created_at).total_seconds() / 3600)
    priority = prioritize(
      risk_score=risk.score if risk else None, risk_level=risk.level if risk else None,
      model_probability=risk.model_probability if risk else None, waiting_hours=waiting, effort=effort,
      high_findings=high,
    )
    ranked.append(Ranked(priority, pull_request, repository, risk, effort, review, shown, high, waiting, pull_request.created_at))
  ranked.sort(key=lambda entry: (-entry.priority.score, entry.created_at, entry.pull_request.id))
  bands = [entry.priority.band for entry in ranked]

  items = []
  for priority, pull_request, repository, risk, effort, review, shown, high, waiting, _ in ranked[:limit]:
    changed = files[pull_request.id]
    reviewers = suggest_reviewers(db, pull_request, [path for path, _, _ in changed])
    items.append(
      QueueItemOut(
        pull_request_id=pull_request.id,
        repository_id=pull_request.repository_id,
        repository=repository,
        number=pull_request.number,
        title=pull_request.title,
        author_login=pull_request.author_login,
        created_at=pull_request.created_at,
        waiting_hours=round(waiting, 1),
        files_changed=len(changed),
        lines_changed=sum(additions + deletions for _, additions, deletions in changed),
        risk_score=risk.score if risk else None,
        risk_level=risk.level if risk else None,
        model_probability=risk.model_probability if risk else None,
        effort=EffortOut(**asdict(effort)),
        priority=priority.score,
        band=priority.band,
        reasons=priority.reasons,
        review_status=review.status if review else None,
        findings_shown=shown,
        findings_high=high,
        suggested_reviewers=[ReviewerOut(**asdict(reviewer)) for reviewer in reviewers],
      )
    )
  return ReviewQueueOut(
    total=len(ranked),
    p1=bands.count("P1"),
    p2=bands.count("P2"),
    p3=bands.count("P3"),
    total_minutes=sum(entry.effort.minutes for entry in ranked),
    not_reviewed=sum(entry.review is None for entry in ranked),
    items=items,
  )
