from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.repo_config import RepoConfigOut
from app.schemas.triage import EffortOut


class EvidenceOut(BaseModel):
  # H diff hunk, F enclosing function, R related code, S signal, L learning, P path
  # instruction, G guideline, C carried over from an earlier review (its kind is kept)
  id: str
  kind: str
  path: str | None  # a file, or a path pattern for learnings and instructions
  start_line: int | None
  end_line: int | None
  text: str
  source_id: int | None = None  # learnings: the learning's id


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
  replacement: str | None  # a one-click fix: the new text of `line` (checked before it is shown)
  original_line: str | None  # the line the replacement replaces
  agent_prompt: str  # an instruction to paste into an AI coding agent
  confidence: float
  evidence: list[EvidenceOut]
  feedback: FeedbackCounts  # on this problem in this PR, across its reviews
  github_comment_id: int | None
  carried_from_review_id: int | None  # incremental reviews: found by this earlier review


class ToolRunOut(BaseModel):
  name: str  # ruff, semgrep, gitleaks
  ran: bool
  findings: int  # on lines the PR added
  error: str | None  # why it did not run, e.g. "not installed"
  duration_ms: int


class ReviewOut(BaseModel):
  id: int
  pull_request_id: int
  pull_request_url: str  # on GitHub
  head_sha: str
  status: str  # completed, or budget_exceeded (stopped before going over the cost budget)
  mode: str  # full, or incremental (only the files changed since base_review_id)
  base_review_id: int | None
  compared_from_sha: str | None
  summary: str | None
  diagram: str | None  # Mermaid sequence diagram of the change
  effort: EffortOut  # estimated review time, from the size of the change
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
  tools: list[ToolRunOut] | None  # static analysis; null: tools are turned off on this server
  config: RepoConfigOut | None  # the repository settings the review applied
  check_state: str | None  # the commit status posted to GitHub: success, failure
  published_at: datetime | None
  created_at: datetime


class FeedbackIn(BaseModel):
  verdict: Literal["useful", "not_useful"]
  # not_useful: why. It is turned into a learning, so future reviews avoid the same mistake.
  reason: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
  id: int
  finding_id: int
  verdict: str | None
  created_at: datetime
  learning_job_id: int | None  # the job turning the reason into a learning


class QueuedJobOut(BaseModel):
  job_id: int
  status: str


class ReviewRunOut(BaseModel):
  """One review run, without its findings: the PR's review history."""

  id: int
  status: str
  mode: str  # full, incremental
  base_review_id: int | None
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
  check_state: str | None
  published_at: datetime | None
  created_at: datetime
