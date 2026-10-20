"""Review triage: effort estimate and priority (suggested reviewers are tested against the database)."""

import pytest

from app.modules.triage import Effort, effort_of_files, estimate_effort, prioritize


@pytest.mark.parametrize(
  ("lines", "files", "level", "minutes"),
  [
    (0, 0, 1, 5),
    (10, 1, 1, 5),
    (11, 1, 2, 15),
    (50, 3, 2, 15),
    (51, 3, 3, 30),
    (200, 3, 3, 30),
    (201, 3, 4, 60),
    (600, 3, 4, 60),
    (601, 3, 5, 120),
    (10, 15, 2, 15),  # many files add a step...
    (5000, 40, 5, 120),  # ...but never past the top
  ],
)
def test_effort_steps(lines, files, level, minutes):
  assert estimate_effort(lines, files) == Effort(level, minutes)


def test_files_nobody_reads_do_not_count_toward_effort():
  files = [("package-lock.json", 4000, 3000), ("dist/app.min.js", 900, 0), ("logo.png", 0, 0), ("app/users.py", 12, 3)]

  assert effort_of_files(files) == Effort(2, 15)  # 15 lines in one file


def test_priority_mixes_risk_model_waiting_and_quick_wins():
  priority = prioritize(
    risk_score=80, risk_level="high", model_probability=0.7, waiting_hours=50, effort=Effort(2, 15), high_findings=1
  )

  # 0.45 * 0.8 + 0.2 * 0.7 + 0.25 * 50/168 + 0.1 * 0.75 + 0.1 for the high finding
  assert priority.score == pytest.approx(0.749, abs=0.001)
  assert priority.band == "P1"
  assert priority.reasons == [
    "risk 80 (high)", "model: 70% chance of rejection", "1 high-severity finding", "waiting 2 days", "quick review (~15 min)",
  ]


def test_bands():
  def band(score_inputs: dict) -> str:
    return prioritize(model_probability=None, effort=Effort(5, 120), **score_inputs).band

  # Without a model the risk counts for 0.45 + 0.2 = 0.65
  assert band({"risk_score": 100, "risk_level": "high", "waiting_hours": 168}) == "P1"  # 0.65 + 0.25
  assert band({"risk_score": 54, "risk_level": "medium", "waiting_hours": 0}) == "P2"  # 0.351
  assert band({"risk_score": 53, "risk_level": "medium", "waiting_hours": 0}) == "P3"  # 0.3445


def test_without_a_model_the_risk_counts_twice_and_waiting_stops_growing_after_a_week():
  week = prioritize(risk_score=0, risk_level="low", model_probability=None, waiting_hours=168, effort=Effort(5, 120))
  month = prioritize(risk_score=0, risk_level="low", model_probability=None, waiting_hours=720, effort=Effort(5, 120))

  assert week.score == month.score == 0.25
  assert month.reasons[-1] == "waiting 30 days"


def test_a_pr_not_scored_yet_counts_as_no_risk():
  priority = prioritize(risk_score=None, risk_level=None, model_probability=None, waiting_hours=0.5, effort=Effort(1, 5))

  assert priority.band == "P3"
  assert priority.reasons == ["risk not scored yet", "opened under an hour ago", "quick review (~5 min)"]
