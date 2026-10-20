from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.code_chunk import EMBEDDING_DIMENSIONS


class Learning(Base):
  """A rule for future reviews of one repository, learned from feedback or written by hand.

  Learnings from GitHub start disabled (proposed): anyone who can comment on a PR could
  write one, so a person approves them in the dashboard first.
  """

  __tablename__ = "learnings"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  repository_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repositories.id"), nullable=False, index=True)
  text: Mapped[str] = mapped_column(Text, nullable=False)
  path_glob: Mapped[str | None] = mapped_column(String(255))  # where it applies; null = everywhere
  # manual (written in the dashboard), dashboard (a 👎 with a reason), github (a reply or "remember")
  source: Mapped[str] = mapped_column(String(20), nullable=False)
  source_finding_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("review_findings.id"))
  enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
  embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
  embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
  times_applied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
  last_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
