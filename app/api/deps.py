"""Dependencies for the routes that use a model: tests replace them with fakes."""

from fastapi import HTTPException

from app.modules.code.embeddings import Embedder, get_embedder
from app.modules.review.llm import LLMError, LLMProvider, get_llm


def get_model() -> LLMProvider:
  try:
    return get_llm()
  except LLMError as error:
    raise HTTPException(status_code=503, detail=f"The model is not available: {error}") from error


def get_text_embedder() -> Embedder:
  try:
    return get_embedder()
  except (ImportError, OSError, ValueError) as error:  # not installed, not downloaded, wrong size
    raise HTTPException(status_code=503, detail=f"The embedding model is not available: {error}") from error
