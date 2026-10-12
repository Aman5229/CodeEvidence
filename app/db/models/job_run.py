from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class JobRun(Base):
  """One background job: what to do (type + payload), and what happened (status, attempts).

  Failed rows are the dead letters: jobs that will not be retried automatically.
  """

  __tablename__ = "job_runs"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  job_type: Mapped[str] = mapped_column(String(50), nullable=False)
  payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
  status: Mapped[str] = mapped_column(String(20), nullable=False)
  attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  last_error: Mapped[str | None] = mapped_column(Text)
  event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("github_events.id"))
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

  __table_args__ = (
    Index("ix_job_runs_status_id", "status", "id"),  # list failed jobs (dead letters)
    Index("ix_job_runs_event_id", "event_id"),  # an event's jobs
  )
