from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
  BigInteger,
  DateTime,
  ForeignKey,
  Index,
  Integer,
  String,
  Text,
  UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
  from app.db.models.pull_request_file import PullRequestFile


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

  # lazy="raise" works like Rails strict_loading: reading pr.files without
  # loading them in the query (selectinload) raises instead of running a hidden query.
  files: Mapped[list["PullRequestFile"]] = relationship(
    order_by="PullRequestFile.path",
    lazy="raise",
  )

  __table_args__ = (
    UniqueConstraint("repository_id","github_pr_id"),
    # Serves the PR list: a repository's PRs newest first, with keyset paging on (created_at, id).
    Index("ix_pull_requests_repository_id_created_at_id", "repository_id", "created_at", "id"),
  )
