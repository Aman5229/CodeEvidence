from datetime import datetime
from sqlalchemy import BigInteger, DateTime, String, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
class GitHubEvent(Base):
  __tablename__ = "github_events"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  github_delivery_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
  event_type: Mapped[str] = mapped_column(String(100), nullable=False)
  action: Mapped[str | None] = mapped_column(String(100))
  repository_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("repositories.id"))
  payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
  status: Mapped[str] = mapped_column(String(30), nullable=False)
  error_message: Mapped[str | None] = mapped_column(Text)
  received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))