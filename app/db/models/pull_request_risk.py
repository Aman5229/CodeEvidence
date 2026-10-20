from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PullRequestRisk(Base):
  """A PR's features (the inputs) and its risk score (the result), one row per PR.

  The feature columns double as the training data for the ML model later.
  """

  __tablename__ = "pull_request_risks"

  pull_request_id: Mapped[int] = mapped_column(
    BigInteger, ForeignKey("pull_requests.id"), primary_key=True
  )
  repository_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repositories.id"), nullable=False)

  files_changed: Mapped[int] = mapped_column(Integer, nullable=False)
  lines_changed: Mapped[int] = mapped_column(Integer, nullable=False)
  log_lines_changed: Mapped[float] = mapped_column(Float, nullable=False)
  test_file_ratio: Mapped[float] = mapped_column(Float, nullable=False)
  docs_only: Mapped[bool] = mapped_column(Boolean, nullable=False)
  is_bot: Mapped[bool] = mapped_column(Boolean, nullable=False)
  size_percentile: Mapped[float] = mapped_column(Float, nullable=False)

  score: Mapped[int] = mapped_column(Integer, nullable=False)
  level: Mapped[str] = mapped_column(String(10), nullable=False)
  reasons: Mapped[list] = mapped_column(JSONB, nullable=False)  # [{"code", "message", "points"}]
  version: Mapped[str] = mapped_column(String(20), nullable=False)  # which rules produced it

  # The trained model's prediction, when a model is loaded (null otherwise)
  model_version: Mapped[str | None] = mapped_column(String(40))
  model_probability: Mapped[float | None] = mapped_column(Float)  # chance of closing unmerged
  model_flagged: Mapped[bool | None] = mapped_column(Boolean)  # probability >= model threshold
  model_inputs: Mapped[list | None] = mapped_column(JSONB)  # the values it saw, for drift checks
  computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

  __table_args__ = (
    # The repository's PR sizes, read to place a new PR within its repository
    Index("ix_pull_request_risks_repository_id_lines", "repository_id", "lines_changed"),
  )
