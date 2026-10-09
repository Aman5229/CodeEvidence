from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.core.pagination import decode_cursor, encode_cursor
from app.db.models import PullRequest, PullRequestFile, Repository
from app.db.session import get_db
from app.schemas.page import Page
from app.schemas.repository import RepositoryOut, RepositoryStats

router = APIRouter(prefix= "/repositories", tags=["repositories"])

@router.get("", response_model=Page[RepositoryOut], responses=error_responses(400, 422))
def list_repositories(
  limit: int = Query(default=20, ge=1, le=100),
  cursor: str | None = Query(default=None),
  db: Session = Depends(get_db),
):
  query = select(Repository).order_by(Repository.id)

  if cursor is not None:
    try:
      last_id = decode_cursor(cursor)[0]
    except (ValueError, IndexError) as error:
      raise HTTPException(status_code=400, detail="Invalid cursor") from error
    if not isinstance(last_id, int):
      raise HTTPException(status_code=400, detail="Invalid cursor")
    query = query.where(Repository.id > last_id)

  rows = db.scalars(query.limit(limit + 1)).all()
  items = rows[:limit]
  next_cursor = encode_cursor([items[-1].id]) if len(rows) > limit else None
  return {"items": items, "next_cursor": next_cursor}



@router.get(
  "/{repository_id}", response_model=RepositoryOut, responses=error_responses(404, 422)
)
def get_repository(repository_id: int, db: Session = Depends(get_db)):
  repository = db.get(Repository, repository_id)

  if repository is None:
    raise HTTPException(status_code=404, detail="Repository not found")

  return repository

def safe_ratio(part: int, whole: int) -> float | None:
  return part / whole if whole else None

@router.get(
  "/{repository_id}/stats",
  response_model=RepositoryStats,
  responses=error_responses(404, 422),
)
def get_repository_stats(repository_id: int, db: Session = Depends(get_db)):
  """
  merge_rate = merged / closed (open PRs are excluded). Medians interpolate
  between the two middle values. Ratios and medians are null when there is no data.
  """
  if db.get(Repository, repository_id) is None:
    raise HTTPException(status_code=404, detail="Repository not found")
  lines_per_pr = (
    select(
      PullRequest.id.label("pull_request_id"),
      func.coalesce(
        func.sum(PullRequestFile.additions + PullRequestFile.deletions), 0
      ).label("lines_changed"),
    )
    .outerjoin(PullRequestFile, PullRequestFile.pull_request_id == PullRequest.id)
    .where(PullRequest.repository_id == repository_id)
    .group_by(PullRequest.id)
    .subquery()
  )

  # Step 2: every number in one query. COUNT(*) FILTER (WHERE ...) counts a subset.
  is_bot = PullRequest.author_login.endswith("[bot]")
  hours_to_close = func.extract("epoch", PullRequest.closed_at - PullRequest.created_at) / 3600

  query = (
    select(
      func.count().label("total_prs"),
      func.count().filter(PullRequest.status == "closed").label("closed_prs"),
      func.count().filter(PullRequest.merged_at.is_not(None)).label("merged_prs"),
      func.count().filter(is_bot).label("bot_prs"),
      func.percentile_cont(0.5)
        .within_group(lines_per_pr.c.lines_changed)
        .label("median_lines_changed"),
      func.percentile_cont(0.5)
        .within_group(hours_to_close)
        .label("median_hours_to_close"),
    )
    .select_from(PullRequest)
    .join(lines_per_pr, lines_per_pr.c.pull_request_id == PullRequest.id)
    .where(PullRequest.repository_id == repository_id)
  )

  row = db.execute(query).one()

  return RepositoryStats(
    repository_id=repository_id,
    total_prs=row.total_prs,
    closed_prs=row.closed_prs,
    merged_prs=row.merged_prs,
    merge_rate=safe_ratio(row.merged_prs, row.closed_prs),
    bot_prs=row.bot_prs,
    bot_share=safe_ratio(row.bot_prs, row.total_prs),
    median_lines_changed=row.median_lines_changed,
    median_hours_to_close=row.median_hours_to_close,
  )