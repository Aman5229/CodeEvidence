"""Compute a PR's risk from the database and store it."""

from collections import defaultdict
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import PullRequest, PullRequestFile, PullRequestRisk
from app.modules.ml.features import author_history, model_inputs
from app.modules.ml.serving import get_risk_model
from app.modules.risk.features import ChangedFile, PullRequestFeatures, extract_features
from app.modules.risk.score import RULES_VERSION, RiskScore, score_pull_request

# Below this many PRs, "large for this repository" means nothing (the first PR would be the
# largest), so the repository-relative size is treated as typical.
MIN_REPO_HISTORY = 20


def compute_risk(db: Session, pull_request_id: int) -> PullRequestRisk:
  """Score one PR (after its files are synced). Safe to run again: the row is replaced."""
  pull_request = db.get(PullRequest, pull_request_id)
  if pull_request is None:
    raise ValueError(f"Pull request {pull_request_id} does not exist")

  files = [
    ChangedFile(path, additions, deletions)
    for path, additions, deletions in db.execute(
      select(PullRequestFile.path, PullRequestFile.additions, PullRequestFile.deletions).where(
        PullRequestFile.pull_request_id == pull_request_id
      )
    )
  ]
  lines_changed = sum(file.additions + file.deletions for file in files)

  # The sizes of the repository's other scored PRs, plus this one: "how big is it, here?"
  others = db.scalars(
    select(PullRequestRisk.lines_changed).where(
      PullRequestRisk.repository_id == pull_request.repository_id,
      PullRequestRisk.pull_request_id != pull_request_id,
    )
  ).all()
  repo_line_counts = sorted([*others, lines_changed]) if len(others) >= MIN_REPO_HISTORY else []

  features = extract_features(files, pull_request.author_login, repo_line_counts)
  earlier = []
  if pull_request.author_login:
    earlier = db.execute(
      select(PullRequest.created_at, PullRequest.merged_at).where(
        PullRequest.repository_id == pull_request.repository_id,
        PullRequest.author_login == pull_request.author_login,
      )
    ).all()
  risk = _store(db, pull_request, features, score_pull_request(features), earlier)
  db.commit()
  return risk


def score_repository(db: Session, repository_id: int) -> int:
  """Score every PR of a repository whose files are synced, against the same, complete size
  baseline. A PR whose files were never fetched is skipped: it would look like a 0-line
  change and get a meaningless score (and become a wrong row of training data).

  Used to (re)score existing data. Returns the number of PRs scored.
  """
  pull_requests = db.scalars(select(PullRequest).where(PullRequest.repository_id == repository_id)).all()
  files_by_pr: dict[int, list[ChangedFile]] = defaultdict(list)
  rows = db.execute(
    select(PullRequestFile.pull_request_id, PullRequestFile.path, PullRequestFile.additions, PullRequestFile.deletions)
    .join(PullRequest, PullRequest.id == PullRequestFile.pull_request_id)
    .where(PullRequest.repository_id == repository_id)
  )
  for pull_request_id, path, additions, deletions in rows:
    files_by_pr[pull_request_id].append(ChangedFile(path, additions, deletions))
  pull_requests = [pull_request for pull_request in pull_requests if files_by_pr[pull_request.id]]

  repo_line_counts = sorted(
    sum(file.additions + file.deletions for file in files_by_pr[pr.id]) for pr in pull_requests
  )
  if len(pull_requests) <= MIN_REPO_HISTORY:
    repo_line_counts = []
  by_author: dict[str | None, list] = defaultdict(list)
  for pull_request in pull_requests:
    by_author[pull_request.author_login].append((pull_request.created_at, pull_request.merged_at))
  for pull_request in pull_requests:
    features = extract_features(files_by_pr[pull_request.id], pull_request.author_login, repo_line_counts)
    earlier = by_author[pull_request.author_login] if pull_request.author_login else []
    _store(db, pull_request, features, score_pull_request(features), earlier)
  db.commit()
  return len(pull_requests)


def _store(
  db: Session,
  pull_request: PullRequest,
  features: PullRequestFeatures,
  result: RiskScore,
  author_prs: list,
) -> PullRequestRisk:
  """Upsert the row. `author_prs` holds (created_at, merged_at) of the author's PRs here."""
  risk = db.get(PullRequestRisk, pull_request.id) or PullRequestRisk(pull_request_id=pull_request.id)
  risk.repository_id = pull_request.repository_id
  for name, value in asdict(features).items():
    setattr(risk, name, value)
  risk.score = result.score
  risk.level = result.level
  risk.reasons = [asdict(reason) for reason in result.reasons]
  risk.version = RULES_VERSION
  # The model's prediction, stored next to the rule score (shadow mode). It doubles as the
  # prediction log that the drift check reads. Without a model, these stay empty.
  model = get_risk_model()
  risk.model_version = risk.model_probability = risk.model_flagged = risk.model_inputs = None
  if model is not None:
    history = author_history(pull_request.created_at, author_prs)
    has_description = bool(pull_request.body and pull_request.body.strip())
    risk.model_inputs = model_inputs(features, history, has_description)
    risk.model_version = model.version
    risk.model_probability = model.probability(risk.model_inputs)
    risk.model_flagged = risk.model_probability >= model.threshold
  risk.computed_at = utc_now()
  db.add(risk)
  return risk
