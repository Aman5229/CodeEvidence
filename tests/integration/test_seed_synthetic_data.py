import statistics

from sqlalchemy import func, select

from app.db.models import PullRequest, PullRequestFile, Repository
from scripts.seed_synthetic_data import OWNER, seed
from tests.integration.test_pull_requests_api import add_pull_request, add_repository


SYNTHETIC_REPO_IDS = select(Repository.id).where(Repository.owner == OWNER)
SYNTHETIC_PR_IDS = select(PullRequest.id).where(PullRequest.repository_id.in_(SYNTHETIC_REPO_IDS))


def synthetic_prs():
  return (
    select(PullRequest)
    .join(Repository, Repository.id == PullRequest.repository_id)
    .where(Repository.owner == OWNER)
  )


def count_rows(db_session, model, ids_column, ids) -> int:
  return db_session.scalar(select(func.count()).select_from(model).where(ids_column.in_(ids)))


def snapshot(db_session) -> list[tuple]:
  """Everything that should be identical between two runs (ids are not)."""
  query = synthetic_prs().order_by(Repository.full_name, PullRequest.number)
  return [
    (pr.number, pr.author_login, pr.status, pr.created_at, pr.closed_at, pr.merged_at)
    for pr in db_session.scalars(query)
  ]


def test_seeds_the_requested_volume(db_session):
  seed(db_session, repos=2, prs_per_repo=50)

  assert count_rows(db_session, Repository, Repository.id, SYNTHETIC_REPO_IDS) == 2
  assert count_rows(db_session, PullRequest, PullRequest.id, SYNTHETIC_PR_IDS) == 100
  assert 150 <= count_rows(db_session, PullRequestFile, PullRequestFile.pull_request_id, SYNTHETIC_PR_IDS) <= 450  # about 3 files per PR


def test_running_twice_gives_identical_data(db_session):
  seed(db_session, repos=2, prs_per_repo=50)
  first = snapshot(db_session)

  seed(db_session, repos=2, prs_per_repo=50)

  assert count_rows(db_session, PullRequest, PullRequest.id, SYNTHETIC_PR_IDS) == 100
  assert snapshot(db_session) == first


def test_real_data_is_untouched(db_session):
  real_repo = add_repository(db_session)
  add_pull_request(db_session, real_repo, 1)

  seed(db_session, repos=1, prs_per_repo=20)
  seed(db_session, repos=1, prs_per_repo=20)

  real_prs = db_session.scalar(
    select(func.count()).select_from(PullRequest).where(PullRequest.repository_id == real_repo.id)
  )
  assert real_prs == 1


def test_data_has_realistic_shape(db_session):
  seed(db_session, repos=1, prs_per_repo=2000)
  prs = db_session.scalars(synthetic_prs()).all()
  closed = [pr for pr in prs if pr.status == "closed"]

  bot_share = sum(pr.author_login.endswith("[bot]") for pr in prs) / len(prs)
  open_share = 1 - len(closed) / len(prs)
  merge_rate = sum(pr.merged_at is not None for pr in closed) / len(closed)
  assert 0.07 <= bot_share <= 0.13
  assert 0.07 <= open_share <= 0.13
  assert 0.30 <= merge_rate <= 0.40

  additions = db_session.scalars(select(PullRequestFile.additions)).all()
  assert statistics.median(additions) < statistics.mean(additions)  # right-skewed, like real PRs
