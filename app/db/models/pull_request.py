from datetime import datetime
from sqlalchemy import BigInteger, String, Text, DateTime, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base
class PullRequest(Base):
  __tablename__ = "pull_requests"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  repository_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repositories.id"), nullable=False)
  github_pr_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
  number: Mapped[int] = mapped_column(Integer, nullable=False)
  title: Mapped[str] = mapped_column(Text, nullable=False)
  body: Mapped[str | None] = mapped_column(Text)
  author_github_id: Mapped[int | None] = mapped_column(BigInteger)
  author_login: Mapped[str | None] = mapped_column(String(255))
  base_branch: Mapped[str] = mapped_column(String(255), nullable=False)
  head_branch: Mapped[str] = mapped_column(String(255), nullable=False)
  base_sha: Mapped[str] = mapped_column(String(40), nullable=False)
  head_sha: Mapped[str] = mapped_column(String(40),nullable=False)
  status: Mapped[str] = mapped_column(String(30),nullable=False)
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
  merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
  ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

  __table_args__ = (UniqueConstraint("repository_id","github_pr_id"),)
