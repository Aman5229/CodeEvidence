from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class EvidenceOut(BaseModel):
  id: str  # H = diff hunk, F = enclosing function, R = related code, S = signal
  kind: str
  path: str | None
  start_line: int | None
  end_line: int | None
  text: str


class FeedbackCounts(BaseModel):
  useful: int
  not_useful: int
  replies: int


class FindingOut(BaseModel):
  id: int
  rank: int
  path: str
  line: int
  severity: str
  category: str
  claim: str
  quote: str
  suggestion: str | None
  confidence: float
  evidence: list[EvidenceOut]
  feedback: FeedbackCounts
  github_comment_id: int | None


class ReviewOut(BaseModel):
  id: int
  pull_request_id: int
  head_sha: str
  status: str  # completed, or budget_exceeded (stopped before going over the cost budget)
  summary: str | None
  findings: list[FindingOut]  # verified, ranked, best first
  dropped_findings: int  # proposed by the model but failed verification
  evidence: list[EvidenceOut]  # everything the model was shown, cited or not
  prompt_version: str
  model: str
  cached: bool  # true: reused from an identical earlier review, no LLM call
  llm_calls: int
  input_tokens: int
  output_tokens: int
  cost_usd: float
  latency_ms: int
  published_at: datetime | None
  created_at: datetime


class FeedbackIn(BaseModel):
  verdict: Literal["useful", "not_useful"]


class FeedbackOut(BaseModel):
  id: int
  finding_id: int
  verdict: str | None
  created_at: datetime


class QueuedJobOut(BaseModel):
  job_id: int
  status: str


class ReviewRunOut(BaseModel):
  """One review run, without its findings: the PR's review history."""

  id: int
  status: str
  model: str
  prompt_version: str
  cached: bool
  llm_calls: int
  input_tokens: int
  output_tokens: int
  cost_usd: float
  latency_ms: int
  findings_shown: int
  findings_dropped: int
  published_at: datetime | None
  created_at: datetime
