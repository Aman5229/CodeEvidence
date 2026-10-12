import logging

from sqlalchemy.orm import Session

from app.db.models import GitHubEvent, PullRequest, Repository
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


def accept_github_event(
  db: Session, *, delivery_id: str, event_type: str, payload: dict
) -> GitHubEvent | None:
  """Store a webhook delivery for processing. Returns None if it was already handled.

  A delivery that failed earlier is returned again, so GitHub's "Redeliver" can retry it.
  """
  event = get_event_by_delivery_id(db, delivery_id)
  if event is not None and event.status != STATUS_FAILED:
    return None

  if event is None:
    event = record_event(
      db,
      delivery_id=delivery_id,
      event_type=event_type,
      action=payload.get("action"),
      payload=payload,
    )
  else:
    logger.info("Retrying previously failed delivery %s", delivery_id)
  db.commit()
  return event


def process_stored_event(db: Session, event_id: int) -> tuple[int | None, int | None]:
  """Turn a stored webhook event into repository and pull request rows. Database only.

  Returns (repository_id, pull_request_id); pull_request_id is None for non-PR events.
  """
  event = db.get(GitHubEvent, event_id)
  if event is None:
    raise ValueError(f"GitHub event {event_id} does not exist")

  try:
    repo_payload = event.payload.get("repository")
    repo = upsert_repository(db, repo_payload) if repo_payload else None
    pr = None
    if event.event_type == "pull_request" and repo is not None:
      pr = upsert_pull_request(db, repo, event.payload["pull_request"])

    status = STATUS_PROCESSED if pr is not None else STATUS_RECEIVED
    mark_event_completed(event, status=status, repository_id=repo.id if repo else None)
    db.commit()
  except Exception as error:
    db.rollback()
    logger.exception("Processing failed for event %s", event_id)
    mark_event_failed(event, error)
    db.commit()
    raise

  return (repo.id if repo else None), (pr.id if pr else None)


async def sync_files_for_pull_request(
  db: Session, github: GitHubClient, pull_request_id: int
) -> int:
  """Fetch the PR's changed files from GitHub and store them. Returns the repository id."""
  pr = db.get(PullRequest, pull_request_id)
  if pr is None:
    raise ValueError(f"Pull request {pull_request_id} does not exist")
  repo = db.get(Repository, pr.repository_id)

  await sync_pull_request_files(db, github, repo, pr)
  db.commit()
  return repo.id
