"""Measure review quality, on hand-labelled findings and on recorded cases replayed in CI.

Labels (one per finding, set by a person):
- useful: correct and worth a reviewer's time.
- wrong: grounded in the code, but the claim is mistaken or not worth a comment.
- not_grounded: talks about code or behaviour that the evidence does not show (hallucination).

Small sets give wide uncertainty, so every rate comes with a 95% Wilson interval. With 50
labels, "70% precision" really means "somewhere between about 56% and 81%".
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.code.evidence import EvidenceBundle
from app.modules.review.llm import CostMeter, FakeLLM
from app.modules.review.pipeline import PipelineResult, run_pipeline

LABELS = ("useful", "wrong", "not_grounded")
REPLAY_BUDGET_USD = 100.0  # replayed answers cost nothing; the budget must not interfere


@dataclass(frozen=True)
class Rate:
  hits: int
  total: int

  @property
  def value(self) -> float | None:
    return self.hits / self.total if self.total else None

  def interval(self, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval: honest for small samples and rates near 0 or 1."""
    if not self.total:
      return None
    p, n = self.hits / self.total, self.total
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)

  def __str__(self) -> str:
    if not self.total:
      return "n/a (no data)"
    low, high = self.interval()
    return f"{self.value:.0%} ({self.hits}/{self.total}, 95% CI {low:.0%} to {high:.0%})"


def percentile(values: list[float], share: float) -> float | None:
  if not values:
    return None
  ordered = sorted(values)
  return ordered[min(len(ordered) - 1, int(round(share * (len(ordered) - 1))))]


# ---------- recorded cases, replayed in CI ----------

@dataclass
class CaseResult:
  name: str
  result: PipelineResult
  labels: dict[tuple[str, str], str]  # (path, quote) -> label

  def label_of(self, finding) -> str | None:
    return self.labels.get((finding.path, " ".join(finding.quote.split())))


@dataclass
class ReplayMetrics:
  shown_precision: Rate  # shown findings labelled useful (unlabelled count as not useful)
  shown_grounded: Rate  # shown findings not labelled not_grounded
  hallucinations_caught: Rate  # findings labelled not_grounded that the verifier dropped
  cases: list[CaseResult] = field(default_factory=list)


def load_case(path: Path) -> dict:
  return json.loads(path.read_text())


def replay_case(case: dict) -> CaseResult:
  """Run the production pipeline on a recorded bundle, with the recorded model answers."""
  bundle = EvidenceBundle.from_json(case["title"], case["description"], case["evidence"])
  # The model's answers in call order: findings (a repair answer, if one was needed), summary
  result = run_pipeline(CostMeter(FakeLLM(case["responses"]), REPLAY_BUDGET_USD), bundle, case.get("risk_level"))
  labels = {(item["path"], " ".join(item["quote"].split())): item["label"] for item in case["labels"]}
  return CaseResult(case["name"], result, labels)


def replay_metrics(cases: list[dict]) -> ReplayMetrics:
  results = [replay_case(case) for case in cases]
  shown = [(r, f) for r in results for f in r.result.ranked]
  proposed = [(r, v) for r in results for v in r.result.verified]
  hallucinated = [v for r, v in proposed if r.label_of(v.finding) == "not_grounded"]
  return ReplayMetrics(
    shown_precision=Rate(sum(r.label_of(f) == "useful" for r, f in shown), len(shown)),
    shown_grounded=Rate(sum(r.label_of(f) != "not_grounded" for r, f in shown), len(shown)),
    hallucinations_caught=Rate(sum(not v.kept for v in hallucinated), len(hallucinated)),
    cases=results,
  )


def gate_failures(metrics: ReplayMetrics, thresholds: dict[str, float]) -> list[str]:
  """The metrics below their threshold, as readable lines. Empty means the gate passes."""
  failures = []
  for name, minimum in thresholds.items():
    rate: Rate = getattr(metrics, name)
    if rate.value is None or rate.value < minimum:
      failures.append(f"{name}: {rate} is below the minimum {minimum:.0%}")
  return failures
