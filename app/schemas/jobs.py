from datetime import datetime

from pydantic import BaseModel, ConfigDict


class JobMessage(BaseModel):
  """What travels through Redis: only the job's id. Its payload is in the job_runs row."""

  job_id: int


class ProcessEventPayload(BaseModel):
  event_id: int


class SyncPullRequestFilesPayload(BaseModel):
  pull_request_id: int


class JobRunOut(BaseModel):
  model_config = ConfigDict(from_attributes=True)

  id: int
  job_type: str
  payload: dict
  status: str
  attempts: int
  last_error: str | None
  event_id: int | None
  created_at: datetime
  updated_at: datetime
  finished_at: datetime | None


class EventOut(BaseModel):
  model_config = ConfigDict(from_attributes=True)

  id: int
  github_delivery_id: str
  event_type: str
  action: str | None
  status: str
  error_message: str | None
  received_at: datetime
  processed_at: datetime | None
  jobs: list[JobRunOut]
