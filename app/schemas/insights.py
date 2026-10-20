from datetime import datetime

from pydantic import BaseModel


class RiskLevels(BaseModel):
  low: int
  medium: int
  high: int


class RecentReview(BaseModel):
  review_id: int
  pull_request_id: int
  number: int
  title: str
  repository: str
  status: str
  model: str
  findings_shown: int
  cost_usd: float
  created_at: datetime


class RiskyPullRequest(BaseModel):
  pull_request_id: int
  number: int
  title: str
  repository: str
  score: int
  level: str


class OverviewOut(BaseModel):
  repositories: int
  pull_requests: int
  reviewed_pull_requests: int
  reviews: int
  findings_shown: int
  findings_dropped: int  # proposed by the model, removed by verification
  feedback_useful: int
  feedback_not_useful: int
  review_cost_usd: float
  risk_levels: RiskLevels
  recent_reviews: list[RecentReview]
  riskiest: list[RiskyPullRequest]


class PullRequestInsight(BaseModel):
  """What a PR list needs beyond the PR itself: its risk and its latest review."""

  pull_request_id: int
  risk_score: int | None
  risk_level: str | None
  model_probability: float | None
  review_status: str | None  # null: never reviewed
  findings_shown: int
  findings_high: int


class IndexStatusOut(BaseModel):
  repository_id: int
  files: int
  chunks: int
  embedding_model: str | None
  last_indexed_at: datetime | None
