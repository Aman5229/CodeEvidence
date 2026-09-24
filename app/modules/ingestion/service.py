import logging

from sqlalchemy.orm import Session

from app.integrations.github.client import GitHubClient
from app.modules.ingestion.event_store import (
  STATUS_FAILED,
  STATUS_PROCESSED,
  STATUS_RECEIVED,
  get_event_by_delivery_id,
  mark_event_completed,
  mark_event_failed,
  record_event,
)
from app.modules.ingestion.file_sync import sync_pull_request_files
from app.modules.ingestion.pull_request_sync import upsert_pull_request
from app.modules.ingestion.repository_sync import upsert_repository

logger = logging.getLogger(__name__)

STATUS_DUPLICATE = "duplicate_ignored"

async def process_github_event(
  db: Session,
  github: GitHubClient,
  *,
  delivery_id: str,
  event_type: str,
  payload: dict,
) -> str:
  """The whole ingestion flow for one GitHub webhook delivery.

  Returns: duplicate_ignored, received, processed, or failed.
  """
  # 1. Idempotency: skip deliveries we already handled.
  #    A FAILED event is allowed through, so GitHub's "Redeliver" can retry it.
  event = get_event_by_delivery_id(db, delivery_id)
  if event is not None and event.status != STATUS_FAILED:
    return STATUS_DUPLICATE

  # 2. Save the raw event FIRST, in its own commit: evidence is never lost.
  if event is None:
    event = record_event(
      db,
      delivery_id=delivery_id,
      event_type=event_type,
      action=payload.get("action"),
      payload=payload,
    )
    db.commit()
  else:
    logger.info("Retrying previously failed delivery %s", delivery_id)

  # 3. Process it. Either ALL derived data is saved, or NONE of it.
  try:
    repository_id, status = await _ingest(db, github, event_type, payload)
    mark_event_completed(event, status=status, repository_id=repository_id)
    db.commit()
    return status
  except Exception as error:
    db.rollback()
    logger.exception("Processing failed for delivery %s", delivery_id)
    mark_event_failed(event, error)
    db.commit()
    return STATUS_FAILED


async def _ingest(
  db: Session, github: GitHubClient, event_type: str, payload: dict
) -> tuple[int | None, str]:
  """Turn the payload into repository / pull request / file rows (no commit here)."""
  repo_payload = payload.get("repository")
  repo = upsert_repository(db, repo_payload) if repo_payload else None
  repository_id = repo.id if repo else None

  if event_type == "pull_request" and repo is not None:
    pr = upsert_pull_request(db, repo, payload["pull_request"])
    await sync_pull_request_files(db, github, repo, pr)
    return repository_id, STATUS_PROCESSED

  return repository_id, STATUS_RECEIVED