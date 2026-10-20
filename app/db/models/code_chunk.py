from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Computed, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

EMBEDDING_DIMENSIONS = 384


class CodeChunk(Base):
  """One function, method or class of a repository's code (default branch), with its
  embedding for vector search and its words for keyword search."""

  __tablename__ = "code_chunks"

  id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
  repository_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repositories.id"), nullable=False)
  path: Mapped[str] = mapped_column(Text, nullable=False)
  blob_sha: Mapped[str] = mapped_column(String(40), nullable=False)  # unchanged SHA = skip on re-index
  language: Mapped[str] = mapped_column(String(20), nullable=False)
  kind: Mapped[str] = mapped_column(String(20), nullable=False)  # function, method, class, window
  name: Mapped[str | None] = mapped_column(Text)
  start_line: Mapped[int] = mapped_column(Integer, nullable=False)
  end_line: Mapped[int] = mapped_column(Integer, nullable=False)
  content: Mapped[str] = mapped_column(Text, nullable=False)
  embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
  embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
  # Identifiers split into words (get_user, getUser -> get user), filled by the indexer
  search_text: Mapped[str] = mapped_column(Text, nullable=False)
  search: Mapped[str] = mapped_column(
    TSVECTOR, Computed("to_tsvector('simple', search_text)", persisted=True)
  )
  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

  __table_args__ = (
    Index("ix_code_chunks_repository_id_path", "repository_id", "path"),
    # Approximate nearest neighbours by cosine distance (HNSW graph)
    Index(
      "ix_code_chunks_embedding",
      "embedding",
      postgresql_using="hnsw",
      postgresql_ops={"embedding": "vector_cosine_ops"},
    ),
    Index("ix_code_chunks_search", "search", postgresql_using="gin"),
  )
