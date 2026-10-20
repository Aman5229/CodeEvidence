from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FindingFeedback(Base):
  """What people thought of a finding: a reaction or reply on GitHub, a resolved thread, or a
  click in the dashboard."""

  __tablename__ = "finding_feedback"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  finding_id: Mapped[int] = mapped_column(
    BigInteger, ForeignKey("review_findings.id"), nullable=False, index=True
  )
  source: Mapped[str] = mapped_column(String(20), nullable=False)  # github_reaction, github_reply, github_resolved, dashboard
  verdict: Mapped[str | None] = mapped_column(String(20))  # useful, not_useful; null for a plain reply
  body: Mapped[str | None] = mapped_column(Text)
  github_user: Mapped[str | None] = mapped_column(String(255))
  # The GitHub object it came from (e.g. "reaction:123"), so collecting twice adds nothing
  external_id: Mapped[str | None] = mapped_column(String(100), unique=True)
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
