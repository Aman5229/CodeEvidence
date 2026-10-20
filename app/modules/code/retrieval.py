"""Find the repository code most related to a piece of a diff.

Two searches, each good at something different, merged:
- Vector search finds code that *means* something similar (pgvector, cosine distance).
- Keyword search finds code that uses the same names (Postgres full-text search).
Reciprocal rank fusion (RRF) merges the two rankings: a chunk ranked high by either, or
fairly high by both, comes first. It needs no tuning of scores that are not comparable.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import CodeChunk
from app.modules.code.embeddings import Embedder
from app.modules.code.tokens import code_tokens

RRF_K = 60  # the usual constant: dampens the difference between rank 1 and rank 2
MAX_QUERY_WORDS = 40
MODES = ("vector", "keyword", "hybrid")


@dataclass(frozen=True)
class RetrievedChunk:
  chunk_id: int
  path: str
  name: str | None
  start_line: int
  end_line: int
  content: str
  score: float
  found_by: tuple[str, ...]  # "vector", "keyword" or both


def reciprocal_rank_fusion(rankings: dict[str, list[int]], k: int = RRF_K) -> list[tuple[int, float, tuple[str, ...]]]:
  """Merge rankings of ids: each id scores the sum of 1 / (k + rank) over the rankings."""
  scores: dict[int, float] = {}
  found_by: dict[int, list[str]] = {}
  for source, ids in rankings.items():
    for rank, chunk_id in enumerate(ids, start=1):
      scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
      found_by.setdefault(chunk_id, []).append(source)
  ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
  return [(chunk_id, scores[chunk_id], tuple(found_by[chunk_id])) for chunk_id in ordered]


def keyword_query(text: str) -> str | None:
  """A full-text query matching any of the text's words: `user | session | expire`."""
  words = list(dict.fromkeys(token for token in code_tokens(text) if token.isalnum()))[:MAX_QUERY_WORDS]
  return " | ".join(words) or None


def vector_ids(db: Session, repository_id: int, vector: list[float], limit: int) -> list[int]:
  return list(
    db.scalars(
      select(CodeChunk.id)
      .where(CodeChunk.repository_id == repository_id)
      .order_by(CodeChunk.embedding.cosine_distance(vector), CodeChunk.id)
      .limit(limit)
    )
  )


def keyword_ids(db: Session, repository_id: int, text: str, limit: int) -> list[int]:
  query_text = keyword_query(text)
  if query_text is None:
    return []
  query = func.to_tsquery("simple", query_text)
  return list(
    db.scalars(
      select(CodeChunk.id)
      .where(CodeChunk.repository_id == repository_id, CodeChunk.search.op("@@")(query))
      .order_by(func.ts_rank_cd(CodeChunk.search, query).desc(), CodeChunk.id)
      .limit(limit)
    )
  )


def retrieve(
  db: Session,
  embedder: Embedder,
  repository_id: int,
  text: str,
  *,
  k: int = 5,
  mode: str = "hybrid",
) -> list[RetrievedChunk]:
  """The k chunks most related to `text`, best first."""
  if mode not in MODES:
    raise ValueError(f"mode must be one of {MODES}")
  candidates = k * 4 if mode == "hybrid" else k  # fusion needs more than k from each side
  rankings: dict[str, list[int]] = {}
  if mode in ("vector", "hybrid"):
    rankings["vector"] = vector_ids(db, repository_id, embedder.embed([text])[0], candidates)
  if mode in ("keyword", "hybrid"):
    rankings["keyword"] = keyword_ids(db, repository_id, text, candidates)

  fused = reciprocal_rank_fusion(rankings)[:k]
  chunks = {chunk.id: chunk for chunk in db.scalars(select(CodeChunk).where(CodeChunk.id.in_([i for i, _, _ in fused])))}
  return [
    RetrievedChunk(
      chunk_id=chunk_id,
      path=chunks[chunk_id].path,
      name=chunks[chunk_id].name,
      start_line=chunks[chunk_id].start_line,
      end_line=chunks[chunk_id].end_line,
      content=chunks[chunk_id].content,
      score=score,
      found_by=found_by,
    )
    for chunk_id, score, found_by in fused
  ]


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
  """Share of the relevant items found in the top k."""
  if not relevant:
    return 0.0
  return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
  """1 / position of the first relevant item (0 when none is found)."""
  for position, item in enumerate(ranked, start=1):
    if item in relevant:
      return 1.0 / position
  return 0.0
