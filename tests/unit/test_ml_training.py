"""Training, evaluation, packaging and serving of the risk model, on synthetic data."""

import csv
from pathlib import Path

import joblib
import numpy as np
import pytest

from app.modules.ml.dataset import COLUMNS, LABEL
from app.modules.ml.drift import drift_status, population_stability_index
from app.modules.ml.features import MODEL_FEATURES
from app.modules.ml.serving import load_model
from app.modules.ml.training import bundle, choose_threshold, evaluate, load_csv, time_split, train


def synthetic_csv(path: Path, rows: int = 400, seed: int = 0) -> Path:
  """Rejection depends on size and author experience, plus noise: a learnable signal."""
  rng = np.random.default_rng(seed)
  with path.open("w", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=COLUMNS)
    writer.writeheader()
    for i in range(rows):
      values = {
        "log_lines_changed": rng.uniform(0, 8),
        "log_files_changed": rng.uniform(0, 3),
        "test_file_ratio": rng.uniform(0, 1),
        "docs_only": float(rng.random() < 0.1),
        "is_bot": float(rng.random() < 0.2),
        "size_percentile": rng.uniform(0, 1),
        "log_author_prior_prs": rng.uniform(0, 4),
        "author_prior_merge_share": rng.uniform(0, 1),
        "has_description": float(rng.random() < 0.8),
      }
      logit = 0.6 * values["log_lines_changed"] - 1.2 * values["log_author_prior_prs"] - 1
      rejected = int(rng.random() < 1 / (1 + np.exp(-logit)))
      writer.writerow(
        {
          "pull_request_id": i + 1,
          "repository": "octo/repo",
          "created_at": f"2026-01-01T00:00:{i:04d}",
          LABEL: rejected,
          "rule_score": round(values["log_lines_changed"] * 10),
          **values,
        }
      )
  return path


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
  dataset = load_csv(synthetic_csv(tmp_path_factory.mktemp("data") / "rows.csv"))
  return dataset, train(dataset)


def test_time_split_keeps_the_newest_rows_for_testing():
  train_idx, test_idx = time_split(10, 0.2)

  assert train_idx.tolist() == list(range(8))
  assert test_idx.tolist() == [8, 9]


def test_metrics_on_a_perfect_and_a_useless_ranking():
  y = np.array([0, 0, 0, 1, 1])

  perfect = evaluate(y, np.array([0.1, 0.2, 0.3, 0.8, 0.9]), threshold=0.5)
  constant = evaluate(y, np.full(5, 0.4), threshold=0.5)

  assert (perfect.roc_auc, perfect.pr_auc, perfect.precision, perfect.recall) == (1.0, 1.0, 1.0, 1.0)
  assert constant.roc_auc == 0.5
  assert constant.precision is None  # nothing flagged
  assert constant.recall == 0.0


def test_threshold_moves_down_when_misses_cost_more():
  y = np.array([0, 0, 0, 0, 1, 1])
  probabilities = np.array([0.1, 0.2, 0.35, 0.4, 0.3, 0.9])

  threshold = choose_threshold(y, probabilities)

  assert threshold <= 0.3  # catching the 0.3 rejection is worth two false alarms


def test_model_learns_the_signal_and_beats_the_majority_baseline(trained):
  _, result = trained

  chosen = list(result.test_metrics.values())[-1]
  assert chosen.roc_auc > 0.7
  assert chosen.pr_auc > result.test_metrics["Majority class"].pr_auc
  assert 0.05 <= result.threshold <= 0.95


def test_explanations_point_at_the_real_signal(trained):
  _, result = trained

  assert result.coefficients["log_lines_changed"] > 0
  assert result.coefficients["log_author_prior_prs"] < 0
  top_two = sorted(result.importances, key=result.importances.get, reverse=True)[:2]
  assert set(top_two) == {"log_lines_changed", "log_author_prior_prs"}


def test_report_parts_are_filled(trained):
  _, result = trained

  assert len(result.worst_misses) == 10
  assert sum(count for _, _, count in result.reliability) == result.test_rows
  assert set(result.cv_pr_auc) == {"logistic_regression", "gradient_boosting"}


def test_training_is_reproducible(tmp_path, trained):
  dataset, result = trained

  again = train(load_csv(synthetic_csv(tmp_path / "rows.csv")))

  assert again.model_name == result.model_name
  assert again.threshold == result.threshold
  assert np.allclose(again.test_probabilities, result.test_probabilities)


def test_saved_model_is_served(tmp_path, trained):
  dataset, result = trained
  path = tmp_path / "model.joblib"
  joblib.dump(bundle(result, dataset, "risk-model-test"), path)

  model = load_model(path)

  assert model.version == "risk-model-test"
  assert 0.0 <= model.probability(dataset.X[0].tolist()) <= 1.0


def test_missing_model_file_means_rules_only(tmp_path):
  assert load_model(tmp_path / "nope.joblib") is None


def test_model_built_for_other_features_is_ignored(tmp_path, trained):
  dataset, result = trained
  saved = bundle(result, dataset, "old")
  saved["features"] = list(MODEL_FEATURES[:-1])
  joblib.dump(saved, tmp_path / "old.joblib")

  assert load_model(tmp_path / "old.joblib") is None


def test_drift_is_zero_for_the_training_distribution_and_large_for_a_shift():
  edges, shares = [0.0, 1.0, 2.0, 3.0], [1 / 3, 1 / 3, 1 / 3]

  same = population_stability_index(edges, shares, [0.5, 1.5, 2.5] * 10)
  shifted = population_stability_index(edges, shares, [2.5] * 30)

  assert same == pytest.approx(0.0, abs=1e-9)
  assert drift_status(same) == "stable"
  assert drift_status(shifted) == "drifted"
