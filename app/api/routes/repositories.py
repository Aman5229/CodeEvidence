from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Repository
from app.db.session import get_db
from app.schemas.page import Page
from app.schemas.repository import RepositoryOut

router = APIRouter(prefix= "/repositories", tags=["repositories"])

@router.get("", response_model=Page[RepositoryOut])
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



@router.get("/{repository_id}", response_model=RepositoryOut)
def get_repository(repository_id: int, db: Session = Depends(get_db)):
  repository = db.get(Repository, repository_id)

  if repository is None:
    raise HTTPException(status_code=404, detail="Repository not found")

  return repository
