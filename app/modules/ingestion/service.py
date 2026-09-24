from sqlalchemy.orm import Session

from app.integrations.github.client import GitHubClient
from app.modules.ingestion.event_store import get_event_by_delivery_id, record_event
from app.modules.ingestion.file_sync import sync_pull_request_files
from app.modules.ingestion.pull_request_sync import upsert_pull_request
from app.modules.ingestion.repository_sync import upsert_repository

STATUS_DUPLICATE = "duplicate_ignored"
STATUS_RECEIVED = "received"
STATUS_PROCESSED = "processed"


async def process_github_event(
  db: Session,
  github: GitHubClient,
  *,
  delivery_id: str,
  event_type: str,
  payload: dict,
) -> str:
  """The whole ingestion flow for one GitHub webhook delivery.

  Returns the status string: duplicate_ignored, received, or processed.
  """
  # 1. Idempotency: GitHub retries deliveries, never process one twice.
  if get_event_by_delivery_id(db, delivery_id) is not None:
    return STATUS_DUPLICATE

  # 2. Repository: most events carry one.
  repo_payload = payload.get("repository")
  repo = upsert_repository(db, repo_payload) if repo_payload else None

  # 3. Pull request + its changed files: only for pull_request events.
  status = STATUS_RECEIVED
  if event_type == "pull_request" and repo is not None:
    pr = upsert_pull_request(db, repo, payload["pull_request"])
    await sync_pull_request_files(db, github, repo, pr)
    status = STATUS_PROCESSED

  # 4. Raw event: stored as evidence, linked to the repository.
  record_event(
    db,
    delivery_id=delivery_id,
    event_type=event_type,
    action=payload.get("action"),
    repository_id=repo.id if repo else None,
    payload=payload,
    status=status,
  )

  # 5. One commit: everything above is saved together, or nothing is.
  db.commit()
  return status
