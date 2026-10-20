from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.db.models import (
  CodeChunk,
  FindingFeedback,
  PullRequest,
  PullRequestRisk,
  Repository,
  Review,
  ReviewFinding,
)
from app.db.session import get_db
from app.schemas.insights import (
  IndexStatusOut,
  OverviewOut,
  PullRequestInsight,
  RecentReview,
  RiskLevels,
  RiskyPullRequest,
)

router = APIRouter(tags=["insights"])

RECENT_REVIEWS = 8
RISKIEST = 5
MAX_INSIGHT_IDS = 100


@router.get("/overview", response_model=OverviewOut, responses=error_responses(422))
def overview(db: Session = Depends(get_db)):
  """Totals for the dashboard: PRs, risk levels, reviews, findings, feedback and cost.

  Findings are counted on reviews that called the model, when the model raised them: reviews
  reused from the cache, and findings an incremental review carried over, would count them twice.
  """
  shown = func.count(ReviewFinding.id).filter(ReviewFinding.rank.is_not(None))
  dropped = func.count(ReviewFinding.id).filter(ReviewFinding.status == "dropped")
  findings_shown, findings_dropped = db.execute(
    select(shown, dropped)
    .join(Review, Review.id == ReviewFinding.review_id)
    .where(Review.cached.is_(False), ReviewFinding.carried_from_review_id.is_(None))
  ).one()
  levels = dict(db.execute(select(PullRequestRisk.level, func.count()).group_by(PullRequestRisk.level)).all())
  verdicts = dict(
    db.execute(select(FindingFeedback.verdict, func.count()).group_by(FindingFeedback.verdict)).all()
  )

  shown_per_review = (
    select(ReviewFinding.review_id, func.count().label("shown"))
    .where(ReviewFinding.rank.is_not(None))
    .group_by(ReviewFinding.review_id)
    .subquery()
  )
  recent = db.execute(
    select(Review, PullRequest.number, PullRequest.title, Repository.full_name, shown_per_review.c.shown)
    .join(PullRequest, PullRequest.id == Review.pull_request_id)
    .join(Repository, Repository.id == PullRequest.repository_id)
    .outerjoin(shown_per_review, shown_per_review.c.review_id == Review.id)
    .order_by(Review.created_at.desc(), Review.id.desc())
    .limit(RECENT_REVIEWS)
  ).all()
  riskiest = db.execute(
    select(PullRequestRisk.score, PullRequestRisk.level, PullRequest.id, PullRequest.number, PullRequest.title, Repository.full_name)
    .join(PullRequest, PullRequest.id == PullRequestRisk.pull_request_id)
    .join(Repository, Repository.id == PullRequest.repository_id)
    .order_by(PullRequestRisk.score.desc(), PullRequest.id.desc())
    .limit(RISKIEST)
  ).all()

  return OverviewOut(
    repositories=db.scalar(select(func.count()).select_from(Repository)),
    pull_requests=db.scalar(select(func.count()).select_from(PullRequest)),
    reviewed_pull_requests=db.scalar(select(func.count(distinct(Review.pull_request_id)))),
    reviews=db.scalar(select(func.count()).select_from(Review)),
    findings_shown=findings_shown,
    findings_dropped=findings_dropped,
    feedback_useful=verdicts.get("useful", 0),
    feedback_not_useful=verdicts.get("not_useful", 0),
    review_cost_usd=round(db.scalar(select(func.coalesce(func.sum(Review.cost_usd), 0.0))), 6),
    risk_levels=RiskLevels(low=levels.get("low", 0), medium=levels.get("medium", 0), high=levels.get("high", 0)),
    recent_reviews=[
      RecentReview(
        review_id=review.id,
        pull_request_id=review.pull_request_id,
        number=number,
        title=title,
        repository=repository,
        status=review.status,
        model=review.model,
        findings_shown=shown_count or 0,
        cost_usd=review.cost_usd,
        created_at=review.created_at,
      )
      for review, number, title, repository, shown_count in recent
    ],
    riskiest=[
      RiskyPullRequest(pull_request_id=pr_id, number=number, title=title, repository=repository, score=score, level=level)
      for score, level, pr_id, number, title, repository in riskiest
    ],
  )


@router.get(
  "/pull-requests/insights",
  response_model=list[PullRequestInsight],
  responses=error_responses(422),
)
def pull_request_insights(
  ids: Annotated[list[int], Query(min_length=1, max_length=MAX_INSIGHT_IDS)],
  db: Session = Depends(get_db),
):
  """Risk and latest-review status for up to 100 PRs at once (`?ids=1&ids=2`), so a PR list
  can show them without one request per row. Unknown ids are left out."""
  risks = {
    risk.pull_request_id: risk
    for risk in db.scalars(select(PullRequestRisk).where(PullRequestRisk.pull_request_id.in_(ids)))
  }
  latest = db.execute(
    select(Review.id, Review.pull_request_id, Review.status)
    .where(Review.pull_request_id.in_(ids))
    .order_by(Review.pull_request_id, Review.created_at.desc(), Review.id.desc())
    .ext(distinct_on(Review.pull_request_id))  # Postgres DISTINCT ON: the newest review of each PR
  ).all()
  counts = {
    review_id: (shown, high)
    for review_id, shown, high in db.execute(
      select(
        ReviewFinding.review_id,
        func.count(),
        func.count().filter(ReviewFinding.severity == "high"),
      )
      .where(ReviewFinding.review_id.in_([row.id for row in latest]), ReviewFinding.rank.is_not(None))
      .group_by(ReviewFinding.review_id)
    )
  }
  reviews = {row.pull_request_id: row for row in latest}
  existing = db.scalars(select(PullRequest.id).where(PullRequest.id.in_(ids))).all()

  insights = []
  for pull_request_id in sorted(existing):
    risk, review = risks.get(pull_request_id), reviews.get(pull_request_id)
    shown, high = counts.get(review.id, (0, 0)) if review else (0, 0)
    insights.append(
      PullRequestInsight(
        pull_request_id=pull_request_id,
        risk_score=risk.score if risk else None,
        risk_level=risk.level if risk else None,
        model_probability=risk.model_probability if risk else None,
        review_status=review.status if review else None,
        findings_shown=shown,
        findings_high=high,
      )
    )
  return insights


@router.get(
  "/repositories/{repository_id}/index",
  response_model=IndexStatusOut,
  responses=error_responses(404, 422),
  tags=["repositories"],
)
def index_status(repository_id: int, db: Session = Depends(get_db)):
  """How much of the repository's code is indexed for retrieval. Queue a (re)index with POST."""
  if db.get(Repository, repository_id) is None:
    raise HTTPException(status_code=404, detail="Repository not found")
  files, chunks, model, last = db.execute(
    select(
      func.count(distinct(CodeChunk.path)),
      func.count(CodeChunk.id),
      func.max(CodeChunk.embedding_model),
      func.max(CodeChunk.created_at),
    ).where(CodeChunk.repository_id == repository_id)
  ).one()
  return IndexStatusOut(
    repository_id=repository_id, files=files, chunks=chunks, embedding_model=model, last_indexed_at=last
  )
