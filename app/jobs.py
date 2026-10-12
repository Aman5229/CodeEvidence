"""Background jobs. Each job has a job_runs row (status, attempts, errors); Celery carries its id."""

import asyncio
import logging
import random
import time
from collections.abc import Callable

from celery import Task
from celery.exceptions import Retry
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.cache import invalidate_pull_request
from app.core.logs import delivery_id_var, job_id_var, request_id_var
from app.db.models import JobRun
from app.db.redis import redis_client
from app.db.session import SessionLocal
from app.integrations.github.client import get_github_client
from app.integrations.github.guard import (
  GitHubGuard,
  GitHubUnavailable,
  is_retryable,
  rate_limit_wait_seconds,
)
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

# Retries: exponential backoff with full jitter, for up to MAX_RETRIES real failures.
# Pauses (GitHub rate-limited or circuit open) wait without using up that budget.
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300
MAX_RETRIES = 5
# Waits stay well below Redis's visibility timeout (1 h): a message held longer is redelivered.
MAX_PAUSE_SECONDS = 900


def retry_delay_seconds(attempt: int) -> float:
  """Full jitter: a random wait between 0 and BASE * 2^attempt, capped at MAX."""
  return random.uniform(0, min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2**attempt))


def retry_countdown(error: Exception, failures: int) -> float:
  """How long to wait before the next try. Pauses get a little jitter so workers don't wake together."""
  if isinstance(error, GitHubUnavailable):
    return min(MAX_PAUSE_SECONDS, error.retry_after) + random.uniform(0, 1)
  rate_limit_wait = rate_limit_wait_seconds(error)
  if rate_limit_wait is not None:
    return min(MAX_PAUSE_SECONDS, rate_limit_wait) + random.uniform(0, 1)
  return retry_delay_seconds(failures)


def get_github_guard() -> GitHubGuard:
  return GitHubGuard(redis_client)


# ---------- the worker side ----------

def run_tracked(task: Task, message: dict, handler: Callable[[Session, JobRun], None]) -> None:
  """Run one job and record it: running, then succeeded, retrying or failed (dead letter).

  The request and delivery ids from the message are restored, so the job's log lines can be
  matched with the webhook request that queued it.
  """
  received = JobMessage.model_validate(message)
  tokens = [
    request_id_var.set(received.request_id),
    delivery_id_var.set(received.delivery_id),
    job_id_var.set(received.job_id),
  ]
  started = time.perf_counter()
  try:
    _run(task, received, handler, started)
  finally:
    for var, token in zip((request_id_var, delivery_id_var, job_id_var), tokens, strict=True):
      var.reset(token)


def _run(task: Task, received: JobMessage, handler, started: float) -> None:
  with SessionLocal() as db:
    job = start_job_run(db, received.job_id)
    logger.info("Job started", extra={"job_type": job.job_type, "attempt": job.attempts})
    try:
      handler(db, job)
    except Exception as error:
      db.rollback()
      paused = isinstance(error, GitHubUnavailable) or rate_limit_wait_seconds(error) is not None
      will_retry = paused or (is_retryable(error) and received.failures < MAX_RETRIES)
      fail_job_run(job, error, will_retry=will_retry)
      db.commit()
      outcome = "paused" if paused else "retrying" if will_retry else "failed"
      log = logger.warning if will_retry else logger.error
      log("Job %s: %s", outcome, error, extra={"job_type": job.job_type, "outcome": outcome})
      if will_retry:
        failures = received.failures if paused else received.failures + 1
        try:
          task.retry(
            args=[received.model_copy(update={"failures": failures}).model_dump()],
            countdown=retry_countdown(error, received.failures),
            exc=error,
          )  # raises Retry once the retry is scheduled
        except Retry:
          raise
        except Exception as retry_error:
          if retry_error is error:
            raise  # called directly, not from the queue: Celery re-raises; nothing to schedule
          # The retry could not be scheduled (e.g. Redis down): make it a visible dead letter
          # instead of leaving it "retrying" with no message to run it.
          fail_job_run(job, retry_error, will_retry=False)
          db.commit()
          raise
      raise
    finish_job_run(job)
    db.commit()
    logger.info(
      "Job succeeded",
      extra={"job_type": job.job_type, "duration_ms": round((time.perf_counter() - started) * 1000, 1)},
    )


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
  guard = get_github_guard()
  guard.before_call()  # raises GitHubUnavailable while rate-limited or the circuit is open
  try:
    repository_id = asyncio.run(
      sync_files_for_pull_request(db, get_github_client(), payload.pull_request_id)
    )
  except Exception as error:
    guard.record_failure(error)
    raise
  guard.record_success()
  invalidate_pull_request(redis_client, repository_id, payload.pull_request_id)


@celery_app.task
def ping(seconds: float = 0) -> str:
  """Proves a job travels from the queue to a worker. `seconds` makes it slow, to test shutdown."""
  time.sleep(seconds)
  return "pong"


# max_retries=None: Celery must not cap retries itself. Its counter also counts pauses, so a
# job that waited out an open circuit a few times would be dropped. run_tracked keeps the budget.
@celery_app.task(bind=True, max_retries=None)
def process_event(self, message: dict) -> None:
  """Stored webhook event -> repository and PR rows; then queue the file sync."""
  run_tracked(self, message, _process_event)


@celery_app.task(bind=True, max_retries=None)
def sync_pr_files(self, message: dict) -> None:
  """Fetch a PR's changed files from GitHub (the slow, failure-prone part)."""
  run_tracked(self, message, _sync_pr_files)


# ---------- the producer side ----------

JOB_TASKS = {task.name.rsplit(".", 1)[-1]: task for task in (process_event, sync_pr_files)}


def new_message(job_id: int) -> JobMessage:
  """A job message that carries the current request and delivery ids to the worker's logs."""
  return JobMessage(job_id=job_id, request_id=request_id_var.get(), delivery_id=delivery_id_var.get())


def dispatch(task: Task, message: JobMessage) -> None:
  """The only place that talks to the broker. Tests replace it with a fake."""
  task.delay(message.model_dump())


def enqueue_job(db: Session, task: Task, payload: BaseModel, *, event_id: int | None) -> JobRun:
  """Record the job, commit, then queue it. If queueing fails, the job is marked failed."""
  job_type = task.name.rsplit(".", 1)[-1]
  job = create_job_run(db, job_type=job_type, payload=payload.model_dump(), event_id=event_id)
  db.commit()  # before queueing, so the worker can already see the row
  try:
    dispatch(task, new_message(job.id))
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
    dispatch(JOB_TASKS[job.job_type], new_message(job.id))
  except Exception as error:
    fail_job_run(job, error, will_retry=False)
    db.commit()
    raise


def enqueue_process_event(db: Session, event_id: int) -> JobRun:
  return enqueue_job(db, process_event, ProcessEventPayload(event_id=event_id), event_id=event_id)
