from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatMessage(Base):
  """One turn of a conversation about a PR: a question, or an answer with its citations."""

  __tablename__ = "chat_messages"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  pull_request_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("pull_requests.id"), nullable=False)
  role: Mapped[str] = mapped_column(String(10), nullable=False)  # user, assistant
  content: Mapped[str] = mapped_column(Text, nullable=False)
  # The evidence it cites: [{"id", "kind", "path", "start_line", "end_line"}]
  citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
  source: Mapped[str] = mapped_column(String(10), nullable=False)  # dashboard, github
  github_user: Mapped[str | None] = mapped_column(String(255))
  github_comment_id: Mapped[int | None] = mapped_column(BigInteger)  # the comment it came from or answered
  model: Mapped[str | None] = mapped_column(String(100))
  input_tokens: Mapped[int | None] = mapped_column(Integer)
  output_tokens: Mapped[int | None] = mapped_column(Integer)
  cost_usd: Mapped[float | None] = mapped_column(Float)
  latency_ms: Mapped[int | None] = mapped_column(Integer)
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

  __table_args__ = (Index("ix_chat_messages_pull_request_id_id", "pull_request_id", "id"),)
