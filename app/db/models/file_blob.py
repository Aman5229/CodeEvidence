from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FileBlob(Base):
  """A file's text, fetched once per content hash (blob SHA) and shared by every PR and
  repository index that contains the exact same file content."""

  __tablename__ = "file_blobs"

  blob_sha: Mapped[str] = mapped_column(String(40), primary_key=True)
  size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
  content: Mapped[str | None] = mapped_column(Text)  # null when skipped
  skipped_reason: Mapped[str | None] = mapped_column(String(20))  # too_large, binary
  fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
