from datetime import datetime
from sqlalchemy import BigInteger, Boolean, Text, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class PullRequestFile(Base):
  __tablename__ = "pull_request_files"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  pull_request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pull_requests.id"), nullable=False)
  path: Mapped[str] = mapped_column(Text, nullable=False)
  previous_path: Mapped[str | None] = mapped_column(Text)
  status: Mapped[str] = mapped_column(Text, nullable=False)
  additions: Mapped[int] = mapped_column(Integer,nullable=False)
  deletions: Mapped[int] = mapped_column(Integer,nullable=False)
  changes: Mapped[int] = mapped_column(Integer,nullable=False)
  patch: Mapped[str | None] = mapped_column(Text)
  patch_size_bytes: Mapped[int | None] = mapped_column(Integer)
  patch_truncated: Mapped[bool] = mapped_column(Boolean,nullable=False,default=False)
  blob_sha: Mapped[str | None] = mapped_column(Text)
  is_stale: Mapped[bool] = mapped_column(Boolean,nullable=False,default=False)
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),nullable=False)
  __table_args__ = (UniqueConstraint("pull_request_id","path",),)
