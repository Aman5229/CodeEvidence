"""Background jobs. Each job has a job_runs row (status, attempts, errors); Celery carries its id."""

import asyncio
import logging
import random
import time
from collections.abc import Callable

import httpx
from celery import Task
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.cache import invalidate_pull_request
from app.db.models import JobRun
from app.db.redis import redis_client
from app.db.session import SessionLocal
from app.integrations.github.client import get_github_client
from app.modules.ingestion.service import process_stored_event, sync_files_for_pull_request
from app.modules.job_runs import (
  create_job_run,
  fail_job_run,
  finish_job_run,
  requeue_job_run,
  start_job_run,
)
from app.schemas.jobs import JobMessage, ProcessEventPayload, SyncPullRequestFilesPayload
from app.worker import celery_app

logger = logging.getLogger(__name__)

# Retries: exponential backoff with full jitter.
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300
MAX_RETRIES = 5
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def is_retryable(error: Exception) -> bool:
  """True for failures that may succeed later: network problems and GitHub overload."""
  if isinstance(error, httpx.TransportError):  # timeouts, connection errors
    return True
  if isinstance(error, httpx.HTTPStatusError):
    return error.response.status_code in RETRYABLE_STATUS_CODES
  return False


def retry_delay_seconds(attempt: int) -> float:
  """Full jitter: a random wait between 0 and BASE * 2^attempt, capped at MAX."""
  return random.uniform(0, min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2**attempt))


# ---------- the worker side ----------

def run_tracked(task: Task, message: dict, handler: Callable[[Session, JobRun], None]) -> None:
  """Run one job and record it: running, then succeeded, retrying or failed (dead letter)."""
  job_id = JobMessage.model_validate(message).job_id
  with SessionLocal() as db:
    job = start_job_run(db, job_id)
    try:
      handler(db, job)
    except Exception as error:
      db.rollback()
      will_retry = is_retryable(error) and task.request.retries < task.max_retries
      fail_job_run(job, error, will_retry=will_retry)
      db.commit()
      if will_retry:
        raise task.retry(exc=error, countdown=retry_delay_seconds(task.request.retries)) from error
      logger.error("Job %s (%s) failed for good: %s", job.id, job.job_type, error)
      raise
    finish_job_run(job)
    db.commit()


def _process_event(db: Session, job: JobRun) -> None:
  payload = ProcessEventPayload.model_validate(job.payload)
  repository_id, pull_request_id = process_stored_event(db, payload.event_id)
  if pull_request_id is not None:
    invalidate_pull_request(redis_client, repository_id, pull_request_id)
    enqueue_job(
      db,
      sync_pr_files,
      SyncPullRequestFilesPayload(pull_request_id=pull_request_id),
      event_id=payload.event_id,
    )


def _sync_pr_files(db: Session, job: JobRun) -> None:
  payload = SyncPullRequestFilesPayload.model_validate(job.payload)
  repository_id = asyncio.run(
    sync_files_for_pull_request(db, get_github_client(), payload.pull_request_id)
  )
  invalidate_pull_request(redis_client, repository_id, payload.pull_request_id)


@celery_app.task
def ping(seconds: float = 0) -> str:
  """Proves a job travels from the queue to a worker. `seconds` makes it slow, to test shutdown."""
  time.sleep(seconds)
  return "pong"


@celery_app.task(bind=True, max_retries=MAX_RETRIES)
def process_event(self, message: dict) -> None:
  """Stored webhook event -> repository and PR rows; then queue the file sync."""
  run_tracked(self, message, _process_event)


@celery_app.task(bind=True, max_retries=MAX_RETRIES)
def sync_pr_files(self, message: dict) -> None:
  """Fetch a PR's changed files from GitHub (the slow, failure-prone part)."""
  run_tracked(self, message, _sync_pr_files)


# ---------- the producer side ----------

JOB_TASKS = {task.name.rsplit(".", 1)[-1]: task for task in (process_event, sync_pr_files)}


def dispatch(task: Task, job_id: int) -> None:
  """The only place that talks to the broker. Tests replace it with a fake."""
  task.delay(JobMessage(job_id=job_id).model_dump())


def enqueue_job(db: Session, task: Task, payload: BaseModel, *, event_id: int | None) -> JobRun:
  """Record the job, commit, then queue it. If queueing fails, the job is marked failed."""
  job_type = task.name.rsplit(".", 1)[-1]
  job = create_job_run(db, job_type=job_type, payload=payload.model_dump(), event_id=event_id)
  db.commit()  # before queueing, so the worker can already see the row
  try:
    dispatch(task, job.id)
  except Exception as error:
    fail_job_run(job, error, will_retry=False)
    db.commit()
    raise
  return job


def retry_failed_job(db: Session, job: JobRun) -> None:
  """Queue a dead letter again. If queueing fails, it stays failed."""
  requeue_job_run(job)
  db.commit()
  try:
    dispatch(JOB_TASKS[job.job_type], job.id)
  except Exception as error:
    fail_job_run(job, error, will_retry=False)
    db.commit()
    raise


def enqueue_process_event(db: Session, event_id: int) -> JobRun:
  return enqueue_job(db, process_event, ProcessEventPayload(event_id=event_id), event_id=event_id)
