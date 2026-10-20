"""Has the data changed since training? Compares recent model inputs with the training data.

Population stability index (PSI) per feature: < 0.1 stable, 0.1 to 0.25 worth watching,
> 0.25 the model is seeing data unlike its training data and should be retrained.
"""

import math

import numpy as np

SMALL = 1e-4  # stands in for an empty bin, so the log stays finite


def population_stability_index(edges: list[float], expected_shares: list[float], values: list[float]) -> float:
  if len(edges) < 2:
    return 0.0  # the feature was constant in training
  counts = np.histogram(np.clip(values, edges[0], edges[-1]), bins=edges)[0]
  actual_shares = counts / max(1, counts.sum())
  return float(
    sum(
      (actual - expected) * math.log(actual / expected)
      for actual, expected in zip(
        (max(SMALL, share) for share in actual_shares),
        (max(SMALL, share) for share in expected_shares),
        strict=True,
      )
    )
  )


def drift_status(psi: float) -> str:
  if psi < 0.1:
    return "stable"
  return "watch" if psi < 0.25 else "drifted"
