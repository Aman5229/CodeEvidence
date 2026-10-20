"""Triage: which PRs to review first, how long each takes, and who knows the code.

Priority (0 to 1) mixes four things, each scaled to 0..1:
- risk: the rule score / 100                                   (weight 0.45)
- model: the trained model's chance of rejection, else risk     (weight 0.20)
- waiting: hours waiting, a full week counts fully              (weight 0.25)
- quick win: small PRs get a little boost                       (weight 0.10)
plus 0.1 when its latest review has high-severity findings. Bands: P1 from 0.6, P2 from 0.35.
These weights are a starting point, chosen by hand; doc/triage.md says how to fit them on
real outcomes later.

Effort: review time estimated from size, in five steps (5 min to 2 h); 15+ files add a step.
Only files a person reads count: lock files, vendored, generated and binary files do not.

Suggested reviewers: people whose merged PRs touched the same files before this PR was
opened (excluding its author and bots), most files touched first, then most recent. With no
one for the exact files, the same top-level folders are used.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import PullRequest, PullRequestFile
from app.modules.code.filters import skip_reason

EFFORT_MINUTES = {1: 5, 2: 15, 3: 30, 4: 60, 5: 120}
EFFORT_LINE_LIMITS = ((10, 1), (50, 2), (200, 3), (600, 4))  # (at most this many lines, level)
MANY_FILES = 15
WEIGHTS = {"risk": 0.45, "model": 0.20, "waiting": 0.25, "quick": 0.10}
HIGH_FINDINGS_BOOST = 0.10
WAITING_FULL_HOURS = 168
BANDS = ((0.60, "P1"), (0.35, "P2"), (0.0, "P3"))
MAX_REVIEWERS = 3


@dataclass(frozen=True)
class Effort:
  level: int  # 1 (trivial) to 5 (large)
  minutes: int


@dataclass(frozen=True)
class Priority:
  score: float
  band: str  # P1, P2, P3
  reasons: list[str]


@dataclass(frozen=True)
class Reviewer:
  login: str
  files_touched: int
  last_touched_at: datetime


def estimate_effort(lines_changed: int, files_changed: int) -> Effort:
  level = next((band for limit, band in EFFORT_LINE_LIMITS if lines_changed <= limit), 5)
  if files_changed >= MANY_FILES:
    level = min(5, level + 1)
  return Effort(level, EFFORT_MINUTES[level])


def effort_of_files(files: list[tuple[str, int, int]]) -> Effort:
  """Effort from (path, additions, deletions) of the changed files a person reads."""
  read = [(additions, deletions) for path, additions, deletions in files if skip_reason(path) is None]
  return estimate_effort(sum(additions + deletions for additions, deletions in read), len(read))


def pull_request_effort(db: Session, pull_request_id: int) -> Effort:
  rows = db.execute(
    select(PullRequestFile.path, PullRequestFile.additions, PullRequestFile.deletions)
    .where(PullRequestFile.pull_request_id == pull_request_id)
  ).all()
  return effort_of_files([(path, additions, deletions) for path, additions, deletions in rows])


def _waiting_text(hours: float) -> str:
  if hours < 1:
    return "opened under an hour ago"
  if hours < 48:
    return f"waiting {round(hours)} h"
  return f"waiting {round(hours / 24)} days"


def prioritize(
  *, risk_score: int | None, risk_level: str | None, model_probability: float | None, waiting_hours: float,
  effort: Effort, high_findings: int = 0,
) -> Priority:
  """risk_score is None for a PR not scored yet (its files are still syncing): it counts as 0."""
  risk = max(0, min(100, risk_score or 0)) / 100
  model = model_probability if model_probability is not None else risk
  waiting = min(1.0, max(0.0, waiting_hours) / WAITING_FULL_HOURS)
  quick = (5 - effort.level) / 4
  score = WEIGHTS["risk"] * risk + WEIGHTS["model"] * model + WEIGHTS["waiting"] * waiting + WEIGHTS["quick"] * quick
  if high_findings:
    score += HIGH_FINDINGS_BOOST
  score = round(min(1.0, score), 3)
  band = next(name for floor, name in BANDS if score >= floor)

  reasons = [f"risk {risk_score} ({risk_level})" if risk_score is not None else "risk not scored yet"]
  if model_probability is not None:
    reasons.append(f"model: {model_probability:.0%} chance of rejection")
  if high_findings:
    reasons.append(f"{high_findings} high-severity finding{'s' if high_findings > 1 else ''}")
  reasons.append(_waiting_text(waiting_hours))
  if effort.level <= 2:
    reasons.append(f"quick review (~{effort.minutes} min)")
  return Priority(score, band, reasons)


def suggest_reviewers(db: Session, pull_request: PullRequest, paths: list[str]) -> list[Reviewer]:
  if not paths:
    return []
  reviewers = _touched(db, pull_request, PullRequestFile.path.in_(paths))
  if reviewers:
    return reviewers
  folders = sorted({PurePosixPath(path).parts[0] for path in paths if len(PurePosixPath(path).parts) > 1})
  if not folders:
    return []
  return _touched(db, pull_request, or_(*(PullRequestFile.path.startswith(folder + "/") for folder in folders)))


def _touched(db: Session, pull_request: PullRequest, path_filter) -> list[Reviewer]:
  rows = db.execute(
    select(
      PullRequest.author_login,
      func.count(func.distinct(PullRequestFile.path)).label("files"),
      func.max(PullRequest.created_at).label("last"),
    )
    .join(PullRequestFile, PullRequestFile.pull_request_id == PullRequest.id)
    .where(
      PullRequest.repository_id == pull_request.repository_id,
      PullRequest.id != pull_request.id,
      PullRequest.created_at < pull_request.created_at,
      PullRequest.merged_at.is_not(None),
      PullRequest.author_login.is_not(None),
      PullRequest.author_login != (pull_request.author_login or ""),
      PullRequest.author_login.not_like("%[bot]"),
      path_filter,
    )
    .group_by(PullRequest.author_login)
    .order_by(func.count(func.distinct(PullRequestFile.path)).desc(), func.max(PullRequest.created_at).desc())
    .limit(MAX_REVIEWERS)
  ).all()
  return [Reviewer(login, files, last) for login, files, last in rows]
