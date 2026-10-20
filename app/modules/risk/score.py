"""Risk score, version 1: hand-picked weighted rules. Every point comes with a reason.

The weights are a first guess, not learned from data. That is the point of this version: it
is easy to explain, and it is the baseline a trained model has to beat later.
"""

from dataclasses import dataclass

from app.modules.risk.features import PullRequestFeatures

RULES_VERSION = "rules-v1"
BASE_POINTS = 10
MEDIUM_FROM = 30
HIGH_FROM = 60


@dataclass(frozen=True)
class Reason:
  code: str  # stable, for programs
  message: str  # for people
  points: int  # how much this reason added (or removed)


@dataclass(frozen=True)
class RiskScore:
  score: int  # 0 to 100
  level: str  # low, medium or high
  reasons: tuple[Reason, ...]


def risk_level(score: int) -> str:
  if score >= HIGH_FROM:
    return "high"
  if score >= MEDIUM_FROM:
    return "medium"
  return "low"


def score_pull_request(features: PullRequestFeatures) -> RiskScore:
  if features.docs_only:
    reason = Reason("docs_only", "Only documentation changed: nothing that runs can break", 0)
    return RiskScore(score=0, level="low", reasons=(reason,))

  reasons: list[Reason] = []
  lines = features.lines_changed
  largest = f"{max(1, round((1 - features.size_percentile) * 100))}%"
  for_repo = f"Among the largest {largest} of this repository's PRs ({lines} lines)"

  # Size, relative to the repository's own PRs (a 200-line PR is big in one repo, normal in another)
  if features.size_percentile >= 0.9:
    reasons.append(Reason("very_large_for_repo", for_repo, 30))
  elif features.size_percentile >= 0.75:
    reasons.append(Reason("large_for_repo", for_repo, 15))

  # Size in absolute terms (a large change is hard to review in any repository)
  if lines >= 500:
    reasons.append(Reason("many_lines", f"{lines} lines changed", 15))

  if features.files_changed >= 20:
    reasons.append(Reason("many_files", f"{features.files_changed} files changed", 15))
  elif features.files_changed >= 10:
    reasons.append(Reason("several_files", f"{features.files_changed} files changed", 8))

  # Tests
  if features.test_file_ratio == 0 and lines >= 50:
    reasons.append(Reason("no_tests", "Changes code but no test files", 20))
  elif features.test_file_ratio >= 0.3:
    reasons.append(Reason("has_tests", "Test files changed along with the code", -10))

  if features.is_bot:
    reasons.append(Reason("bot_author", "Opened by a bot: usually a routine dependency update", -10))

  if not reasons:
    reasons.append(Reason("typical_change", "A typical change for this repository", 0))

  score = max(0, min(100, BASE_POINTS + sum(reason.points for reason in reasons)))
  return RiskScore(score=score, level=risk_level(score), reasons=tuple(reasons))
