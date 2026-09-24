from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
class Repository(Base):
  __tablename__ = "repositories"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  github_repo_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
  owner: Mapped[str] = mapped_column(String(255), nullable=False)
  full_name: Mapped[str] = mapped_column(String(255), nullable=False)
  default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
  html_url: Mapped[str] = mapped_column(String(255), nullable=False)
  is_private: Mapped[bool] = mapped_column(Boolean, nullable=False)
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)