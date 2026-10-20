from datetime import date

from pydantic import BaseModel


class VotesOut(BaseModel):
  useful: int
  not_useful: int


class CategoryStatsOut(BaseModel):
  category: str
  shown: int
  useful: int
  not_useful: int
  acceptance: float | None  # useful / (useful + not useful); null: no votes


class WeekStatsOut(BaseModel):
  week: date  # its Monday
  reviews: int
  cost_usd: float
  proposed: int
  dropped: int
  shown: int
  useful: int
  not_useful: int


class ModelStatsOut(BaseModel):
  model: str
  prompt_version: str
  reviews: int
  cached: int
  avg_cost_usd: float | None  # per review that called the model
  avg_latency_ms: int | None
  findings_shown: int
  findings_dropped: int
  useful: int
  not_useful: int
  acceptance: float | None


class RiskOutcomeOut(BaseModel):
  level: str
  closed: int
  merged: int
  merge_rate: float | None


class DirectoryStatsOut(BaseModel):
  directory: str
  findings: int
  high: int


class DropReasonOut(BaseModel):
  reason: str
  count: int


class ToolStatsOut(BaseModel):
  name: str
  runs: int
  findings: int  # on added lines
  skipped: int  # not installed or failed


class AnalyticsOut(BaseModel):
  days: int
  repository_id: int | None
  reviews: int
  reviews_cached: int
  reviews_incremental: int
  cost_usd: float
  findings_proposed: int
  findings_dropped: int
  findings_shown: int
  votes: VotesOut
  acceptance: float | None
  repeats_after_rejection: int
  learnings_total: int
  learnings_enabled: int
  learnings_proposed: int
  learnings_applied: int
  chat_questions: int
  chat_cost_usd: float
  categories: list[CategoryStatsOut]
  weeks: list[WeekStatsOut]
  models: list[ModelStatsOut]
  risk_outcomes: list[RiskOutcomeOut]
  directories: list[DirectoryStatsOut]
  drop_reasons: list[DropReasonOut]
  tools: list[ToolStatsOut]
