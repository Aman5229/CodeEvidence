from datetime import datetime

from pydantic import BaseModel


class EffortOut(BaseModel):
  level: int  # 1 (trivial) to 5 (large)
  minutes: int  # estimated review time


class ReviewerOut(BaseModel):
  login: str
  files_touched: int  # of this PR's files (or folders), in their earlier merged PRs
  last_touched_at: datetime


class QueueItemOut(BaseModel):
  pull_request_id: int
  repository_id: int
  repository: str
  number: int
  title: str
  author_login: str | None
  created_at: datetime
  waiting_hours: float
  files_changed: int
  lines_changed: int
  risk_score: int | None  # null: not scored yet
  risk_level: str | None
  model_probability: float | None
  effort: EffortOut
  priority: float  # 0 to 1
  band: str  # P1 (review first), P2, P3
  reasons: list[str]
  review_status: str | None  # of the latest review; null: never reviewed
  findings_shown: int
  findings_high: int
  suggested_reviewers: list[ReviewerOut]


class ReviewQueueOut(BaseModel):
  total: int  # open PRs, all of them (items holds the first `limit`)
  p1: int
  p2: int
  p3: int
  total_minutes: int  # estimated time to review all of them
  not_reviewed: int  # open PRs with no AI review
  items: list[QueueItemOut]  # highest priority first
