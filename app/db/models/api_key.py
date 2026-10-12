from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApiKey(Base):
  """A client allowed to call the read API. Only a hash of the key is stored."""

  __tablename__ = "api_keys"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  name: Mapped[str] = mapped_column(String(100), nullable=False)
  key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)  # to recognise a key in lists
  key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # SHA-256, hex
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
  revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
