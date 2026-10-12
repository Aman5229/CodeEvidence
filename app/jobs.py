import asyncio
from collections.abc import Callable

from app.core.cache import invalidate_pull_request
from app.db.redis import redis_client
from app.db.session import SessionLocal
from app.integrations.github.client import get_github_client
from app.modules.ingestion.service import process_stored_event, sync_files_for_pull_request
from app.schemas.jobs import ProcessEventPayload, SyncPullRequestFilesPayload
from app.worker import celery_app


def get_event_queue() -> Callable[[int], None]:
  """FastAPI dependency: how the webhook queues an event. Tests replace it with a fake."""
  return enqueue_process_event


@celery_app.task
def ping() -> str:
  """Proves a job travels from the queue to a worker. Used to check the worker is alive."""
  return "pong"


@celery_app.task
def process_event(payload: dict) -> None:
  """Stored webhook event -> repository and PR rows; then queue the file sync."""
  job = ProcessEventPayload.model_validate(payload)
  with SessionLocal() as db:
    repository_id, pull_request_id = process_stored_event(db, job.event_id)

  if pull_request_id is not None:
    invalidate_pull_request(redis_client, repository_id, pull_request_id)
    enqueue_sync_pr_files(pull_request_id)


@celery_app.task
def sync_pr_files(payload: dict) -> None:
  """Fetch a PR's changed files from GitHub (the slow, failure-prone part)."""
  job = SyncPullRequestFilesPayload.model_validate(payload)
  with SessionLocal() as db:
    repository_id = asyncio.run(
      sync_files_for_pull_request(db, get_github_client(), job.pull_request_id)
    )
  invalidate_pull_request(redis_client, repository_id, job.pull_request_id)


def enqueue_process_event(event_id: int) -> None:
  process_event.delay(ProcessEventPayload(event_id=event_id).model_dump())


def enqueue_sync_pr_files(pull_request_id: int) -> None:
  sync_pr_files.delay(SyncPullRequestFilesPayload(pull_request_id=pull_request_id).model_dump())
