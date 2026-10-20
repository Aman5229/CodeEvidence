from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
  from app.db.models.finding_feedback import FindingFeedback


class Review(Base):
  """One AI review run of a PR at one commit: what it cost and how it was produced."""

  __tablename__ = "reviews"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  pull_request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pull_requests.id"), nullable=False)
  head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
  status: Mapped[str] = mapped_column(String(20), nullable=False)  # completed, budget_exceeded
  prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
  model: Mapped[str] = mapped_column(String(100), nullable=False)
  # Same diff + prompt + model = same key: the earlier result is reused, no LLM call
  cache_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
  cached: Mapped[bool] = mapped_column(Boolean, nullable=False)
  summary: Mapped[str | None] = mapped_column(Text)
  llm_calls: Mapped[int] = mapped_column(Integer, nullable=False)
  input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
  output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
  cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
  latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
  evidence: Mapped[list] = mapped_column(JSONB, nullable=False)  # the items findings may cite
  error: Mapped[str | None] = mapped_column(Text)
  github_review_id: Mapped[int | None] = mapped_column(BigInteger)  # set once posted to GitHub
  published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  # How it was made: "full", or "incremental" (only files changed since base_review_id)
  mode: Mapped[str] = mapped_column(String(12), nullable=False, default="full", server_default="full")
  base_review_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("reviews.id"))
  compared_from_sha: Mapped[str | None] = mapped_column(String(40))
  config: Mapped[dict | None] = mapped_column(JSONB)  # the repository settings it applied
  diagram: Mapped[str | None] = mapped_column(Text)  # Mermaid sequence diagram of the change
  tools: Mapped[list | None] = mapped_column(JSONB)  # static analysis runs: name, ran, findings
  check_state: Mapped[str | None] = mapped_column(String(10))  # commit status posted: success, failure

  findings: Mapped[list["ReviewFinding"]] = relationship(
    order_by="ReviewFinding.id", lazy="raise", back_populates="review"
  )

  __table_args__ = (Index("ix_reviews_pull_request_id_created_at", "pull_request_id", "created_at"),)


class ReviewFinding(Base):
  """One finding the model proposed. Dropped findings are kept too, to measure hallucination."""

  __tablename__ = "review_findings"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  review_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("reviews.id"), nullable=False, index=True)
  path: Mapped[str] = mapped_column(Text, nullable=False)
  line: Mapped[int] = mapped_column(Integer, nullable=False)
  severity: Mapped[str] = mapped_column(String(10), nullable=False)  # low, medium, high
  category: Mapped[str] = mapped_column(String(20), nullable=False)
  claim: Mapped[str] = mapped_column(Text, nullable=False)
  quote: Mapped[str] = mapped_column(Text, nullable=False)  # the code the claim is about
  suggestion: Mapped[str | None] = mapped_column(Text)
  confidence: Mapped[float] = mapped_column(Float, nullable=False)
  evidence: Mapped[list] = mapped_column(JSONB, nullable=False)  # cited evidence ids
  status: Mapped[str] = mapped_column(String(10), nullable=False)  # kept, dropped
  drop_reason: Mapped[str | None] = mapped_column(String(40))
  rank: Mapped[int | None] = mapped_column(Integer)  # 1 = shown first; null when not shown
  # Stable across runs (path, category, quote): avoids posting the same comment twice
  finding_key: Mapped[str] = mapped_column(String(32), nullable=False)
  github_comment_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
  # A one-click fix: the new text for `line`, checked before it is shown (null when none)
  replacement: Mapped[str | None] = mapped_column(Text)
  original_line: Mapped[str | None] = mapped_column(Text)  # the line the replacement replaces
  replacement_rejected: Mapped[str | None] = mapped_column(String(20))  # why a proposed fix was refused
  # Incremental reviews keep findings on files that did not change; this is where they came
  # from (informational, so no foreign key: review_findings already references reviews)
  carried_from_review_id: Mapped[int | None] = mapped_column(BigInteger)

  review: Mapped[Review] = relationship(back_populates="findings", lazy="raise")
  feedback: Mapped[list["FindingFeedback"]] = relationship(order_by="FindingFeedback.id", lazy="raise")
