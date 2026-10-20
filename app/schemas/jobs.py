from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class JobMessage(BaseModel):
  """What travels through Redis: the job's id (its payload is in the job_runs row), how many
  times it has failed so far, and the ids that tie its logs to the webhook request. New fields
  have defaults, so messages sent by older code are still valid."""

  job_id: int
  failures: int = 0
  request_id: str | None = None
  delivery_id: str | None = None


class ProcessEventPayload(BaseModel):
  event_id: int


class SyncPullRequestFilesPayload(BaseModel):
  pull_request_id: int


class IndexRepositoryPayload(BaseModel):
  repository_id: int


class ReviewPullRequestPayload(BaseModel):
  pull_request_id: int
  mode: Literal["auto", "full"] = "auto"  # auto: only the changes since the last review, when possible


class PublishReviewPayload(BaseModel):
  review_id: int


class DistillLearningPayload(BaseModel):
  """Turn a reviewer's reason for rejecting a finding into a learning."""

  finding_id: int
  reason: str
  source: Literal["dashboard", "github"]


class AnswerMentionPayload(BaseModel):
  """A PR comment that mentions @codeevidence: a command or a question."""

  pull_request_id: int
  comment_id: int
  kind: Literal["issue", "review"]  # the PR conversation, or an inline review thread
  body: str
  author: str | None = None
  in_reply_to_id: int | None = None  # review threads: the comment that started the thread


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
