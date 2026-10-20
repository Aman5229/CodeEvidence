"""The evaluation gate: recorded model answers replayed through the real pipeline in CI."""

import json
from pathlib import Path

import pytest

import app.modules.review.pipeline as pipeline
from app.modules.review.evaluation import Rate, gate_failures, load_case, percentile, replay_metrics
from app.modules.review.publishing import MARKER, comment_body, posted_keys
from app.modules.review.verification import Verified

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
CASES = [load_case(path) for path in sorted((EVAL_DIR / "cases").glob("*.json"))]
THRESHOLDS = json.loads((EVAL_DIR / "thresholds.json").read_text())


def test_recorded_cases_pass_the_quality_gate():
  metrics = replay_metrics(CASES)

  assert gate_failures(metrics, THRESHOLDS) == []


def test_the_gate_fails_when_verification_is_broken(monkeypatch):
  """A deliberate regression: keep every finding the model proposes."""
  monkeypatch.setattr(pipeline, "verify", lambda finding, bundle: Verified(finding, True, None))

  failures = gate_failures(replay_metrics(CASES), THRESHOLDS)

  assert any(line.startswith("shown_grounded") for line in failures)
  assert any(line.startswith("hallucinations_caught") for line in failures)


def test_cases_cover_injection_and_repair():
  results = {case.name: case.result for case in replay_metrics(CASES).cases}

  assert results["prompt-injection"].verified[0].drop_reason == "path_not_in_diff"
  repaired = results["malformed-then-repaired"].ranked
  assert [(f.line, f.quote) for f in repaired] == [(22, "if value.expired():")]  # line corrected


def test_wilson_interval_is_wide_for_small_samples():
  small, large = Rate(7, 10).interval(), Rate(700, 1000).interval()

  assert small[0] < 0.45 and small[1] > 0.85
  assert large[1] - large[0] < 0.06
  assert Rate(0, 0).value is None
  assert "n/a" in str(Rate(0, 0))


def test_percentile():
  assert percentile([5, 1, 3, 2, 4], 0.5) == 3
  assert percentile([], 0.95) is None


# ---------- publishing markers ----------

class StoredFinding:
  severity, category, claim, suggestion, confidence = "high", "bug", "It breaks.", None, 0.8
  evidence, finding_key = ["H1"], "a" * 32


def test_comment_carries_a_hidden_key_and_it_is_found_again():
  body = comment_body(StoredFinding())

  assert body.endswith(MARKER.format(key="a" * 32))
  assert posted_keys([{"id": 7, "body": body}, {"id": 8, "body": "a human comment"}]) == {"a" * 32: 7}


@pytest.mark.parametrize("body", [None, "", "<!-- codeevidence:short -->"])
def test_other_comments_are_ignored(body):
  assert posted_keys([{"id": 1, "body": body}]) == {}
