from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import parse_iso_timestamp, utc_now
from app.db.models import Repository


def upsert_repository(db: Session, repo_payload: dict) -> Repository:
  """Return the stored repository for this GitHub repo, creating it if new."""
  existing = db.execute(
    select(Repository).where(Repository.github_repo_id == repo_payload["id"])
  ).scalar_one_or_none()

  if existing is not None:
    return existing

  now = utc_now()
  repo = Repository(
    github_repo_id=repo_payload["id"],
    owner=repo_payload["owner"]["login"],
    full_name=repo_payload["full_name"],
    default_branch=repo_payload["default_branch"],
    html_url=repo_payload["html_url"],
    is_private=repo_payload["private"],
    created_at=parse_iso_timestamp(repo_payload["created_at"]),
    updated_at=parse_iso_timestamp(repo_payload["updated_at"]),
    ingested_at=now,
    last_synced_at=now,
  )
  db.add(repo)
  db.flush()
  return repo
