from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import GitHubEvent


def get_event_by_delivery_id(db: Session, delivery_id: str) -> GitHubEvent | None:
  return db.execute(
    select(GitHubEvent).where(GitHubEvent.github_delivery_id == delivery_id)
  ).scalar_one_or_none()


def record_event(
  db: Session,
  *,
  delivery_id: str,
  event_type: str,
  action: str | None,
  repository_id: int | None,
  payload: dict,
  status: str,
) -> GitHubEvent:
  event = GitHubEvent(
    github_delivery_id=delivery_id,
    event_type=event_type,
    action=action,
    repository_id=repository_id,
    payload=payload,
    status=status,
    received_at=utc_now(),
  )
  db.add(event)
  db.flush()
  return event
