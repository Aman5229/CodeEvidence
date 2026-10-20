"""The training table: one row per closed PR, with leak-free inputs and the label.

Label: `rejected` = 1 when the PR was closed without being merged. It is known only after
the fact, so it is never used as an input.

Every row is built as if the PR had just been opened: its size is compared only with the
repository's *earlier* PRs, and the author's history only counts earlier PRs. The stored
risk rows cannot be reused as-is, because rescoring compares each PR with all of the
repository's PRs, later ones included.
"""

import csv
from bisect import insort
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PullRequest, PullRequestFile, PullRequestRisk, Repository
from app.modules.ml.features import MODEL_FEATURES, AuthorHistory, author_history, model_inputs
from app.modules.risk.features import ChangedFile, extract_features
from app.modules.risk.score import score_pull_request
from app.modules.risk.service import MIN_REPO_HISTORY

LABEL = "rejected"
COLUMNS = ("pull_request_id", "repository", "created_at", LABEL, "rule_score", *MODEL_FEATURES)


@dataclass(frozen=True)
class PullRequestRecord:
  pull_request_id: int
  repository: str
  author_login: str | None
  created_at: datetime
  merged_at: datetime | None
  has_description: bool
  files: tuple[ChangedFile, ...]


def build_rows(records: Iterable[PullRequestRecord]) -> list[dict]:
  """Rows ordered by creation time (oldest first), ready for a time-based split."""
  by_repository: dict[str, list[PullRequestRecord]] = defaultdict(list)
  for record in records:
    by_repository[record.repository].append(record)

  rows = []
  for repository, records_here in by_repository.items():
    records_here.sort(key=lambda record: (record.created_at, record.pull_request_id))
    earlier_sizes: list[int] = []  # sorted line counts of the PRs opened before
    earlier_by_author: dict[str, list[tuple[datetime, datetime | None]]] = defaultdict(list)

    for record in records_here:
      lines = sum(file.additions + file.deletions for file in record.files)
      baseline: list[int] = []
      if len(earlier_sizes) >= MIN_REPO_HISTORY:
        baseline = list(earlier_sizes)
        insort(baseline, lines)
      features = extract_features(list(record.files), record.author_login, baseline)
      history = (
        author_history(record.created_at, earlier_by_author[record.author_login])
        if record.author_login
        else AuthorHistory(0, 0)
      )
      inputs = model_inputs(features, history, record.has_description)
      rows.append(
        {
          "pull_request_id": record.pull_request_id,
          "repository": repository,
          "created_at": record.created_at.isoformat(),
          LABEL: int(record.merged_at is None),
          "rule_score": score_pull_request(features).score,
          **dict(zip(MODEL_FEATURES, inputs, strict=True)),
        }
      )
      insort(earlier_sizes, lines)
      if record.author_login:
        earlier_by_author[record.author_login].append((record.created_at, record.merged_at))

  rows.sort(key=lambda row: (row["created_at"], row["pull_request_id"]))
  return rows


def load_records(db: Session) -> list[PullRequestRecord]:
  """Closed PRs whose files are synced (they have a risk row), with their files."""
  pull_requests = db.execute(
    select(PullRequest, Repository.full_name)
    .join(Repository, Repository.id == PullRequest.repository_id)
    .join(PullRequestRisk, PullRequestRisk.pull_request_id == PullRequest.id)
    .where(PullRequest.closed_at.is_not(None))
  ).all()
  files: dict[int, list[ChangedFile]] = defaultdict(list)
  for pull_request_id, path, additions, deletions in db.execute(
    select(
      PullRequestFile.pull_request_id,
      PullRequestFile.path,
      PullRequestFile.additions,
      PullRequestFile.deletions,
    ).join(PullRequestRisk, PullRequestRisk.pull_request_id == PullRequestFile.pull_request_id)
  ):
    files[pull_request_id].append(ChangedFile(path, additions, deletions))

  return [
    PullRequestRecord(
      pull_request_id=pull_request.id,
      repository=full_name,
      author_login=pull_request.author_login,
      created_at=pull_request.created_at,
      merged_at=pull_request.merged_at,
      has_description=bool(pull_request.body and pull_request.body.strip()),
      files=tuple(files[pull_request.id]),
    )
    for pull_request, full_name in pull_requests
  ]


def write_csv(rows: list[dict], path: Path) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("w", newline="") as file:
    writer = csv.DictWriter(file, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
