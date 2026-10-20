"""Embeddings: text -> a list of numbers, where similar code gets nearby vectors.

Two implementations behind one interface:
- LocalEmbedder runs an open-source model on this machine (no API key, no cost per call).
- FakeEmbedder hashes words into a vector: deterministic and instant, for tests and CI.
  Texts sharing words still end up close, so retrieval tests stay meaningful.
"""

import hashlib
import math
from functools import lru_cache
from typing import Protocol

from app.core.config import settings
from app.db.models.code_chunk import EMBEDDING_DIMENSIONS
from app.modules.code.tokens import code_tokens

BATCH_SIZE = 32


class Embedder(Protocol):
  model_name: str

  def embed(self, texts: list[str]) -> list[list[float]]:
    """One vector of EMBEDDING_DIMENSIONS numbers per text, scaled to length 1."""
    ...


class FakeEmbedder:
  model_name = "fake-hashing-384"

  def embed(self, texts: list[str]) -> list[list[float]]:
    return [self._embed_one(text) for text in texts]

  def _embed_one(self, text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in [*code_tokens(text), "__bias__"]:  # the bias keeps empty texts non-zero
      digest = hashlib.md5(token.encode()).digest()  # stable across runs, unlike hash()
      index = int.from_bytes(digest[:4], "little") % EMBEDDING_DIMENSIONS
      vector[index] += 1.0 if digest[4] % 2 else -1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class LocalEmbedder:
  """A sentence-transformers model. Needs `pip install -e ".[embeddings]"`; the model is
  downloaded on first use and cached."""

  def __init__(self, model_name: str) -> None:
    from sentence_transformers import SentenceTransformer  # heavy import, only when used

    self.model_name = model_name
    self._model = SentenceTransformer(model_name)
    # Renamed in newer sentence-transformers releases; support both
    dimension_of = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
    dimensions = dimension_of()
    if dimensions != EMBEDDING_DIMENSIONS:
      raise ValueError(f"{model_name} makes {dimensions}-number vectors; the database stores {EMBEDDING_DIMENSIONS}")

  def embed(self, texts: list[str]) -> list[list[float]]:
    vectors = self._model.encode(texts, batch_size=BATCH_SIZE, normalize_embeddings=True)
    return vectors.tolist()


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
  if settings.embedding_provider == "fake":
    return FakeEmbedder()
  return LocalEmbedder(settings.embedding_model)
