"""Load the trained model and score PRs with it. Without a usable model file, nothing breaks:
the rule score is still served, and the model part of the answer is empty (fallback).
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib

from app.core.config import settings
from app.modules.ml.features import MODEL_FEATURES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RiskModel:
  version: str
  threshold: float  # probabilities at or above it are flagged
  estimator: object

  def probability(self, inputs: list[float]) -> float:
    """Chance (0 to 1) that the PR is closed without being merged."""
    return float(self.estimator.predict_proba([inputs])[0][1])


def load_model(path: Path) -> RiskModel | None:
  """None when the file is missing, unreadable, or built for different features.

  joblib files are pickles: loading one can run code. Only load files this project trained.
  """
  if not path.exists():
    logger.info("No risk model at %s: serving rule scores only", path)
    return None
  try:
    saved = joblib.load(path)
  except Exception:
    logger.exception("Could not load the risk model at %s: serving rule scores only", path)
    return None
  if saved.get("features") != list(MODEL_FEATURES):
    logger.warning("Risk model %s was trained on other features: ignored", saved.get("version"))
    return None
  return RiskModel(version=saved["version"], threshold=saved["threshold"], estimator=saved["estimator"])


@lru_cache(maxsize=1)
def get_risk_model() -> RiskModel | None:
  """Loaded once per process, on first use."""
  return load_model(Path(settings.risk_model_path))
