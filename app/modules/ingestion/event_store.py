from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import GitHubEvent

STATUS_RECEIVED = "received"
STATUS_PROCESSED = "processed"
STATUS_FAILED = "failed"

MAX_ERROR_MESSAGE_LENGTH = 2000


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
  payload: dict,
) -> GitHubEvent:
  """Store the raw event as 'received'; the repository is linked after processing."""
  event = GitHubEvent(
    github_delivery_id=delivery_id,
    event_type=event_type,
    action=action,
    payload=payload,
    status=STATUS_RECEIVED,
    received_at=utc_now(),
  )
  db.add(event)
  db.flush()
  return event


def mark_event_completed(event: GitHubEvent, *, status: str, repository_id: int | None) -> None:
  """Processing succeeded: link the repository and record the final status."""
  event.status = status
  event.repository_id = repository_id
  event.error_message = None
  if status == STATUS_PROCESSED:
    event.processed_at = utc_now()


def mark_event_failed(event: GitHubEvent, error: Exception) -> None:
  """Processing failed: keep the event, record what went wrong."""
  event.status = STATUS_FAILED
  event.error_message = f"{type(error).__name__}: {error}"[:MAX_ERROR_MESSAGE_LENGTH]
