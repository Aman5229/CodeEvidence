"""The life of a background job in the database: queued -> running -> succeeded / retrying / failed."""

from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import JobRun

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_RETRYING = "retrying"
JOB_SUCCEEDED = "succeeded"
JOB_FAILED = "failed"  # a dead letter: will not be retried automatically

MAX_ERROR_LENGTH = 2000


def create_job_run(db: Session, *, job_type: str, payload: dict, event_id: int | None) -> JobRun:
  now = utc_now()
  job = JobRun(
    job_type=job_type,
    payload=payload,
    status=JOB_QUEUED,
    attempts=0,
    event_id=event_id,
    created_at=now,
    updated_at=now,
  )
  db.add(job)
  db.flush()
  return job


def start_job_run(db: Session, job_id: int) -> JobRun:
  job = db.get(JobRun, job_id)
  if job is None:
    raise ValueError(f"Job {job_id} does not exist")
  job.status = JOB_RUNNING
  job.attempts += 1
  job.updated_at = utc_now()
  db.commit()
  return job


def finish_job_run(job: JobRun) -> None:
  job.status = JOB_SUCCEEDED
  job.last_error = None
  job.updated_at = job.finished_at = utc_now()


def fail_job_run(job: JobRun, error: Exception, *, will_retry: bool) -> None:
  job.status = JOB_RETRYING if will_retry else JOB_FAILED
  job.last_error = f"{type(error).__name__}: {error}"[:MAX_ERROR_LENGTH]
  job.updated_at = utc_now()
  if not will_retry:
    job.finished_at = job.updated_at


def requeue_job_run(job: JobRun) -> None:
  """A person decided to try a dead letter again."""
  job.status = JOB_QUEUED
  job.finished_at = None
  job.updated_at = utc_now()
