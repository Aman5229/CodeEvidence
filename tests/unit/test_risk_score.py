"""Risk score rules (T57): every score lists its reasons."""

from dataclasses import replace

import pytest

from app.modules.risk.features import PullRequestFeatures
from app.modules.risk.score import BASE_POINTS, risk_level, score_pull_request

TYPICAL = PullRequestFeatures(
  files_changed=3,
  lines_changed=40,
  log_lines_changed=3.7,
  test_file_ratio=0.0,
  docs_only=False,
  is_bot=False,
  size_percentile=0.5,
)


def codes(result) -> list[str]:
  return [reason.code for reason in result.reasons]


def test_typical_change_gets_the_base_score_and_a_reason():
  result = score_pull_request(TYPICAL)

  assert result.score == BASE_POINTS
  assert result.level == "low"
  assert codes(result) == ["typical_change"]


def test_large_risky_change_scores_high_with_every_reason():
  features = replace(
    TYPICAL, files_changed=25, lines_changed=1200, size_percentile=0.97, test_file_ratio=0.0
  )

  result = score_pull_request(features)

  assert codes(result) == ["very_large_for_repo", "many_lines", "many_files", "no_tests"]
  assert result.score == BASE_POINTS + 30 + 15 + 15 + 20
  assert result.level == "high"
  assert result.reasons[0].message == "Among the largest 3% of this repository's PRs (1200 lines)"


def test_points_add_up_to_the_score():
  for features in [
    TYPICAL,
    replace(TYPICAL, size_percentile=0.8, files_changed=12),
    replace(TYPICAL, test_file_ratio=0.5, is_bot=True),
  ]:
    result = score_pull_request(features)
    expected = max(0, min(100, BASE_POINTS + sum(r.points for r in result.reasons)))
    assert result.score == expected


def test_the_largest_pr_is_described_sensibly():
  result = score_pull_request(replace(TYPICAL, lines_changed=9000, size_percentile=1.0))

  assert result.reasons[0].message == "Among the largest 1% of this repository's PRs (9000 lines)"


def test_docs_only_is_zero_whatever_the_size():
  result = score_pull_request(replace(TYPICAL, docs_only=True, lines_changed=5000, size_percentile=1.0))

  assert (result.score, result.level, codes(result)) == (0, "low", ["docs_only"])


def test_tests_and_bots_lower_the_score_but_never_below_zero():
  result = score_pull_request(replace(TYPICAL, test_file_ratio=0.5, is_bot=True))

  assert codes(result) == ["has_tests", "bot_author"]
  assert result.score == 0


def test_small_change_without_tests_is_not_flagged():
  """Under 50 lines, missing tests is normal (typo fixes, small tweaks)."""
  assert "no_tests" not in codes(score_pull_request(replace(TYPICAL, lines_changed=12)))


def test_size_relative_to_the_repository_matters():
  normal_here = score_pull_request(replace(TYPICAL, lines_changed=300, size_percentile=0.6))
  huge_here = score_pull_request(replace(TYPICAL, lines_changed=300, size_percentile=0.95))

  assert huge_here.score > normal_here.score


@pytest.mark.parametrize(("score", "level"), [(0, "low"), (29, "low"), (30, "medium"), (59, "medium"), (60, "high"), (100, "high")])
def test_levels(score, level):
  assert risk_level(score) == level


def test_every_score_has_at_least_one_reason():
  for features in [TYPICAL, replace(TYPICAL, docs_only=True), replace(TYPICAL, lines_changed=0, files_changed=0)]:
    assert score_pull_request(features).reasons
