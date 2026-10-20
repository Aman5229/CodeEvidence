from datetime import datetime

from pydantic import BaseModel


class RiskReasonOut(BaseModel):
  code: str
  message: str
  points: int


class RiskFeaturesOut(BaseModel):
  files_changed: int
  lines_changed: int
  log_lines_changed: float
  test_file_ratio: float
  docs_only: bool
  is_bot: bool
  size_percentile: float


class ModelScoreOut(BaseModel):
  version: str
  probability: float  # chance (0 to 1) that the PR is closed without being merged
  flagged: bool  # probability is at or above the model's chosen threshold


class RiskOut(BaseModel):
  pull_request_id: int
  score: int  # 0 to 100
  level: str  # low, medium or high
  reasons: list[RiskReasonOut]
  features: RiskFeaturesOut
  model: ModelScoreOut | None  # null when no trained model is loaded: the rule score still applies
  version: str
  computed_at: datetime
