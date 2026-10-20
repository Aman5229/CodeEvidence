"""Train and evaluate the risk model on the exported dataset. Needs no database.

Steps, in order:
1. Time-based split: the newest 20% of PRs is the test set, never seen during training.
2. Baselines: always predict the majority class; the rule score; lines changed alone.
3. Logistic regression and gradient-boosted trees, tuned with time-ordered cross-validation
   on the training set only.
4. The better model (by cross-validated PR-AUC) is calibrated on the newest part of the
   training set, so its output can be read as a probability.
5. The threshold is chosen on that same calibration part from the cost of each error.
6. Everything is reported on the test set once, at the end.
"""

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sklearn
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.modules.ml.dataset import LABEL
from app.modules.ml.features import MODEL_FEATURES

RANDOM_STATE = 42
TEST_SHARE = 0.2  # newest PRs held out for the final evaluation
CALIBRATION_SHARE = 0.2  # newest part of the training set, used to calibrate and pick the threshold
CV_FOLDS = 5
# Missing a PR that ends up rejected costs more than a false alarm on one that is fine.
FALSE_NEGATIVE_COST = 3.0
FALSE_POSITIVE_COST = 1.0


@dataclass
class Dataset:
  X: np.ndarray
  y: np.ndarray
  rule_scores: np.ndarray
  pull_request_ids: list[int]
  repositories: list[str]
  created_at: list[str]
  sha256: str = ""


@dataclass
class Metrics:
  roc_auc: float | None
  pr_auc: float | None
  precision: float | None  # at the chosen threshold
  recall: float | None
  precision_top_10: float | None  # among the 10% highest scores

  def as_row(self) -> list[str]:
    return [_fmt(value) for value in (self.roc_auc, self.pr_auc, self.precision, self.recall, self.precision_top_10)]


@dataclass
class TrainingResult:
  model_name: str  # "logistic_regression" or "gradient_boosting"
  estimator: object  # calibrated, ready for predict_proba
  threshold: float
  train_rows: int
  test_rows: int
  positive_share: float
  test_metrics: dict[str, Metrics]  # name -> metrics, baselines included
  cv_pr_auc: dict[str, float]
  coefficients: dict[str, float]  # logistic regression, on scaled inputs
  importances: dict[str, float]  # permutation importance (drop in PR-AUC), test set
  reliability: list[tuple[float, float, int]]  # (mean predicted, observed rate, count) per bin
  segments: dict[str, Metrics]  # bots vs people, test set
  worst_misses: list[dict] = field(default_factory=list)
  test_probabilities: np.ndarray | None = None


def load_csv(path: Path) -> Dataset:
  raw = path.read_bytes()
  with path.open(newline="") as file:
    rows = sorted(csv.DictReader(file), key=lambda row: (row["created_at"], int(row["pull_request_id"])))
  if not rows:
    raise ValueError(f"{path} has no rows")
  return Dataset(
    X=np.array([[float(row[name]) for name in MODEL_FEATURES] for row in rows]),
    y=np.array([int(row[LABEL]) for row in rows]),
    rule_scores=np.array([float(row["rule_score"]) for row in rows]),
    pull_request_ids=[int(row["pull_request_id"]) for row in rows],
    repositories=[row["repository"] for row in rows],
    created_at=[row["created_at"] for row in rows],
    sha256=hashlib.sha256(raw).hexdigest(),
  )


def time_split(n: int, test_share: float) -> tuple[np.ndarray, np.ndarray]:
  """Rows are oldest first: the last `test_share` of them is the test set."""
  cut = int(round(n * (1 - test_share)))
  return np.arange(cut), np.arange(cut, n)


def evaluate(y: np.ndarray, scores: np.ndarray, threshold: float) -> Metrics:
  """Ranking quality (ROC-AUC, PR-AUC, top 10%) and errors at one threshold."""
  both_classes = len(set(y.tolist())) == 2
  flagged = scores >= threshold
  top = np.argsort(-scores, kind="stable")[: max(1, len(scores) // 10)]
  return Metrics(
    roc_auc=float(roc_auc_score(y, scores)) if both_classes else None,
    pr_auc=float(average_precision_score(y, scores)) if both_classes else None,
    precision=float(y[flagged].mean()) if flagged.any() else None,
    recall=float(flagged[y == 1].mean()) if (y == 1).any() else None,
    precision_top_10=float(y[top].mean()),
  )


def choose_threshold(y: np.ndarray, probabilities: np.ndarray) -> float:
  """The cut-off with the lowest total cost of errors (ties go to the higher threshold)."""
  best_threshold, best_cost = 0.5, float("inf")
  for threshold in np.round(np.arange(0.05, 0.96, 0.01), 2):
    flagged = probabilities >= threshold
    cost = (
      FALSE_NEGATIVE_COST * np.sum(~flagged & (y == 1)) + FALSE_POSITIVE_COST * np.sum(flagged & (y == 0))
    )
    if cost <= best_cost:
      best_threshold, best_cost = float(threshold), cost
  return best_threshold


def reliability_table(y: np.ndarray, probabilities: np.ndarray, bins: int = 5) -> list[tuple[float, float, int]]:
  """For each probability band: mean predicted probability, observed rejection rate, PR count."""
  observed, predicted = calibration_curve(y, probabilities, n_bins=bins, strategy="quantile")
  edges = np.quantile(probabilities, np.linspace(0, 1, bins + 1))
  counts = np.histogram(probabilities, bins=np.unique(edges))[0]
  return [
    (float(p), float(o), int(c)) for p, o, c in zip(predicted, observed, counts[: len(predicted)], strict=False)
  ]


def _logistic_search(folds: TimeSeriesSplit) -> GridSearchCV:
  pipeline = make_pipeline(
    StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000)
  )
  return GridSearchCV(
    pipeline, {"logisticregression__C": [0.01, 0.1, 1.0, 10.0]}, scoring="average_precision", cv=folds
  )


def _boosting_search(folds: TimeSeriesSplit) -> GridSearchCV:
  model = HistGradientBoostingClassifier(
    random_state=RANDOM_STATE, class_weight="balanced", early_stopping=False
  )
  grid = {"max_depth": [2, 3], "learning_rate": [0.05, 0.1], "max_iter": [100, 200], "min_samples_leaf": [20, 50]}
  return GridSearchCV(model, grid, scoring="average_precision", cv=folds)


def train(dataset: Dataset) -> TrainingResult:
  X, y = dataset.X, dataset.y
  if len(set(y.tolist())) < 2:
    raise ValueError("The label has only one class: a model cannot learn anything")
  train_idx, test_idx = time_split(len(y), TEST_SHARE)
  fit_idx, calibration_idx = time_split(len(train_idx), CALIBRATION_SHARE)
  X_fit, y_fit = X[train_idx][fit_idx], y[train_idx][fit_idx]
  X_cal, y_cal = X[train_idx][calibration_idx], y[train_idx][calibration_idx]
  X_test, y_test = X[test_idx], y[test_idx]

  folds = TimeSeriesSplit(n_splits=CV_FOLDS)
  searches = {"logistic_regression": _logistic_search(folds), "gradient_boosting": _boosting_search(folds)}
  for search in searches.values():
    search.fit(X_fit, y_fit)
  cv_pr_auc = {name: float(search.best_score_) for name, search in searches.items()}
  best_name = max(cv_pr_auc, key=cv_pr_auc.get)

  calibrated = CalibratedClassifierCV(FrozenEstimator(searches[best_name].best_estimator_), method="sigmoid")
  calibrated.fit(X_cal, y_cal)
  threshold = choose_threshold(y_cal, calibrated.predict_proba(X_cal)[:, 1])
  probabilities = calibrated.predict_proba(X_test)[:, 1]

  # Baselines get the same treatment: a threshold chosen on the calibration part.
  majority = float(y_fit.mean() >= 0.5)
  rule_cal = dataset.rule_scores[train_idx][calibration_idx] / 100
  lines_index = MODEL_FEATURES.index("log_lines_changed")
  lines_cal = X_cal[:, lines_index] / max(1e-9, X[:, lines_index].max())
  test_metrics = {
    "Majority class": evaluate(y_test, np.full(len(y_test), majority), 0.5),
    "Rule score (rules-v1)": evaluate(
      y_test, dataset.rule_scores[test_idx] / 100, choose_threshold(y_cal, rule_cal)
    ),
    "Lines changed only": evaluate(
      y_test, X_test[:, lines_index] / max(1e-9, X[:, lines_index].max()), choose_threshold(y_cal, lines_cal)
    ),
  }
  for name, search in searches.items():
    raw = search.best_estimator_.predict_proba(X_test)[:, 1]
    test_metrics[_LABELS[name]] = evaluate(y_test, raw, 0.5)
  test_metrics[f"Chosen: {_LABELS[best_name]}, calibrated"] = evaluate(y_test, probabilities, threshold)

  logistic = searches["logistic_regression"].best_estimator_[-1]
  coefficients = dict(zip(MODEL_FEATURES, (float(c) for c in logistic.coef_[0]), strict=True))
  importance = permutation_importance(
    calibrated, X_test, y_test, scoring="average_precision", n_repeats=10, random_state=RANDOM_STATE
  )
  importances = dict(zip(MODEL_FEATURES, (float(v) for v in importance.importances_mean), strict=True))

  is_bot = X_test[:, MODEL_FEATURES.index("is_bot")] == 1
  segments = {
    "People": evaluate(y_test[~is_bot], probabilities[~is_bot], threshold),
    "Bots": evaluate(y_test[is_bot], probabilities[is_bot], threshold) if is_bot.any() else None,
  }

  return TrainingResult(
    model_name=best_name,
    estimator=calibrated,
    threshold=threshold,
    train_rows=len(train_idx),
    test_rows=len(test_idx),
    positive_share=float(y.mean()),
    test_metrics=test_metrics,
    cv_pr_auc=cv_pr_auc,
    coefficients=coefficients,
    importances=importances,
    reliability=reliability_table(y_test, probabilities),
    segments={name: metrics for name, metrics in segments.items() if metrics is not None},
    worst_misses=_worst_misses(dataset, test_idx, probabilities, threshold),
    test_probabilities=probabilities,
  )


_LABELS = {"logistic_regression": "Logistic regression", "gradient_boosting": "Gradient-boosted trees"}


def _worst_misses(dataset: Dataset, test_idx: np.ndarray, probabilities: np.ndarray, threshold: float) -> list[dict]:
  """The 10 most confident wrong predictions on the test set, for error analysis."""
  y = dataset.y[test_idx]
  wrong = np.flatnonzero((probabilities >= threshold) != (y == 1))
  wrong = wrong[np.argsort(-np.abs(probabilities[wrong] - threshold), kind="stable")][:10]
  return [
    {
      "pull_request_id": dataset.pull_request_ids[test_idx[i]],
      "repository": dataset.repositories[test_idx[i]],
      "probability": float(probabilities[i]),
      "actual": "rejected" if y[i] else "merged",
      **dict(zip(MODEL_FEATURES, (float(v) for v in dataset.X[test_idx[i]]), strict=True)),
    }
    for i in wrong
  ]


def feature_bins(X: np.ndarray, bins: int = 10) -> dict[str, dict]:
  """Each feature's training distribution (bin edges and shares), for the drift check."""
  result = {}
  for index, name in enumerate(MODEL_FEATURES):
    edges = np.unique(np.quantile(X[:, index], np.linspace(0, 1, bins + 1)))
    counts = np.histogram(np.clip(X[:, index], edges[0], edges[-1]), bins=edges)[0] if len(edges) > 1 else np.array([len(X)])
    result[name] = {"edges": edges.tolist(), "shares": (counts / counts.sum()).tolist()}
  return result


def bundle(result: TrainingResult, dataset: Dataset, version: str) -> dict:
  """Everything needed to serve and audit the model, saved together in one file."""
  return {
    "version": version,
    "features": list(MODEL_FEATURES),
    "estimator": result.estimator,
    "threshold": result.threshold,
    "metadata": {
      "model": result.model_name,
      "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
      "dataset_sha256": dataset.sha256,
      "rows": {"train": result.train_rows, "test": result.test_rows},
      "data_window": [dataset.created_at[0], dataset.created_at[-1]],
      "sklearn_version": sklearn.__version__,
      "test_metrics": {name: vars(metrics) for name, metrics in result.test_metrics.items()},
      "feature_bins": feature_bins(dataset.X),
    },
  }


def _fmt(value: float | None) -> str:
  return "n/a" if value is None else f"{value:.3f}"
