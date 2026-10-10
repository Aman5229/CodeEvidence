from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from redis import Redis
from sqlalchemy import not_, or_, select, tuple_
from sqlalchemy.orm import Session, selectinload

from app.api.errors import error_responses
from app.core.pagination import decode_cursor, encode_cursor
from app.db.models import PullRequest, Repository
from app.db.session import get_db
from app.schemas.page import Page
from app.db.redis import get_redis

from app.core.cache import get_or_set, params_hash

from app.schemas.pull_request import (
  PullRequestDetail,
  PullRequestDetailWithPatch,
  PullRequestSummary,
)

router = APIRouter(tags=["pull-requests"])


@router.get(
  "/repositories/{repository_id}/pull-requests",
  response_model=Page[PullRequestSummary],
  responses=error_responses(400, 404, 422),
)
def list_pull_requests(
  repository_id: int,
  status: Literal["open", "closed"] | None = None,
  merged: bool | None = None,
  author: str | None = None,
  is_bot: bool | None = None,
  created_after: datetime | None = None,
  created_before: datetime | None = None,
  limit: int = Query(default=20, ge=1, le=100),
  cursor: str | None = None,
  db: Session = Depends(get_db),
  cache: Redis = Depends(get_redis),
) -> Response:
  """
  Newest first. Pass `next_cursor` from a response as `cursor` to get the
  next page; it is null on the last page. All filters can be combined.
  """
  inputs = {
    "status": status,
    "merged": merged,
    "author": author,
    "is_bot": is_bot,
    "created_after": created_after,
    "created_before": created_before,
    "limit": limit,
    "cursor": cursor,
  }
  key = f"pull_requests:{repository_id}:{params_hash(inputs)}"

  def build() -> str:
    if db.get(Repository, repository_id) is None:
      raise HTTPException(status_code=404, detail="Repository not found")

    query = select(PullRequest).where(PullRequest.repository_id == repository_id)

    if status is not None:
      query = query.where(PullRequest.status == status)

    if merged is not None:
      if merged:
        query = query.where(PullRequest.merged_at.is_not(None))
      else:
        query = query.where(PullRequest.merged_at.is_(None))

    if author is not None:
      query = query.where(PullRequest.author_login == author)

    if is_bot is not None:
      looks_like_bot = PullRequest.author_login.endswith("[bot]")
      if is_bot:
        query = query.where(looks_like_bot)
      else:
        query = query.where(or_(PullRequest.author_login.is_(None), not_(looks_like_bot)))

    if created_after is not None:
      query = query.where(PullRequest.created_at >= created_after)

    if created_before is not None:
      query = query.where(PullRequest.created_at < created_before)

    query = query.order_by(PullRequest.created_at.desc(), PullRequest.id.desc())

    if cursor is not None:
      try:
        last_created_text, last_id = decode_cursor(cursor)
        last_created = datetime.fromisoformat(last_created_text)
      except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail="Invalid cursor") from error
      if not isinstance(last_id, int):
        raise HTTPException(status_code=400, detail="Invalid cursor")
      query = query.where(
        tuple_(PullRequest.created_at, PullRequest.id) < tuple_(last_created, last_id)
      )

    rows = db.scalars(query.limit(limit + 1)).all()
    items = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
      last = items[-1]
      next_cursor = encode_cursor([last.created_at.isoformat(), last.id])
    return Page[PullRequestSummary](items=items, next_cursor=next_cursor).model_dump_json()

  return Response(content=get_or_set(cache, key, build), media_type="application/json")


# response_model=None because the shape depends on include_patch: we pick the
# schema ourselves below. `responses` keeps the full shape visible in /docs.
@router.get(
  "/pull-requests/{pull_request_id}",
  response_model=None,
  responses={200: {"model": PullRequestDetailWithPatch}, **error_responses(404, 422)},
)
def get_pull_request(
  pull_request_id: int,
  include_patch: bool = False,
  db: Session = Depends(get_db),
  cache: Redis = Depends(get_redis),
) -> Response:
  """Patches are left out unless `include_patch=true`."""
  key = f"pull_request:{pull_request_id}:patch={int(include_patch)}"

  def build() -> str:
    # selectinload = Rails preload: one query for the PR, one for all its files.
    query = (
      select(PullRequest)
      .where(PullRequest.id == pull_request_id)
      .options(selectinload(PullRequest.files))
    )
    pull_request = db.scalars(query).one_or_none()
    if pull_request is None:
      raise HTTPException(status_code=404, detail="Pull request not found")

    schema = PullRequestDetailWithPatch if include_patch else PullRequestDetail
    return schema.model_validate(pull_request).model_dump_json()

  return Response(content=get_or_set(cache, key, build), media_type="application/json")
