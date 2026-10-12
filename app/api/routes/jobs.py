from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import error_responses
from app.core.pagination import decode_cursor, encode_cursor
from app.db.models import JobRun
from app.db.session import get_db
from app.jobs import retry_failed_job
from app.modules.job_runs import JOB_FAILED
from app.schemas.jobs import JobRunOut
from app.schemas.page import Page

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=Page[JobRunOut], responses=error_responses(400, 422))
def list_jobs(
  status: Literal["queued", "running", "retrying", "succeeded", "failed"] = "failed",
  limit: int = Query(default=20, ge=1, le=100),
  cursor: str | None = None,
  db: Session = Depends(get_db),
):
  """
  Background jobs, newest first. By default the dead letters: jobs that failed for good
  (a non-retryable error, or out of retries). Retry one with POST /jobs/{job_id}/retry.
  """
  query = select(JobRun).where(JobRun.status == status).order_by(JobRun.id.desc())
  if cursor is not None:
    try:
      last_id = decode_cursor(cursor)[0]
    except (ValueError, IndexError) as error:
      raise HTTPException(status_code=400, detail="Invalid cursor") from error
    if not isinstance(last_id, int):
      raise HTTPException(status_code=400, detail="Invalid cursor")
    query = query.where(JobRun.id < last_id)

  rows = db.scalars(query.limit(limit + 1)).all()
  items = rows[:limit]
  next_cursor = encode_cursor([items[-1].id]) if len(rows) > limit else None
  return {"items": items, "next_cursor": next_cursor}


@router.post(
  "/{job_id}/retry",
  status_code=202,
  response_model=JobRunOut,
  responses=error_responses(404, 409, 422, 503),
)
def retry_job(job_id: int, db: Session = Depends(get_db)):
  """Queue a failed job (a dead letter) again, after the cause has been fixed."""
  job = db.get(JobRun, job_id)
  if job is None:
    raise HTTPException(status_code=404, detail="Job not found")
  if job.status != JOB_FAILED:
    raise HTTPException(status_code=409, detail=f"Only failed jobs can be retried (status: {job.status})")

  try:
    retry_failed_job(db, job)
  except Exception as error:
    raise HTTPException(status_code=503, detail="Job could not be queued") from error
  return job
