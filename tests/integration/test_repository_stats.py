from datetime import timedelta

import pytest

from app.db.models import PullRequestFile
from tests.integration.test_pull_requests_api import (
  START,
  add_pull_request,
  add_repository,
)


def close_after(db_session, pull_request, hours: float) -> None:
  pull_request.closed_at = pull_request.created_at + timedelta(hours=hours)
  db_session.commit()


def add_file(db_session, pull_request, path: str, additions: int, deletions: int) -> None:
  db_session.add(
    PullRequestFile(
      pull_request_id=pull_request.id,
      path=path,
      status="modified",
      additions=additions,
      deletions=deletions,
      changes=additions + deletions,
      patch_truncated=False,
      is_stale=False,
      created_at=START,
    )
  )
  db_session.commit()


@pytest.fixture
def repository(db_session):
  """
  4 PRs, chosen so every stat has one clear right answer:

  PR | author           | state           | closed after | lines
  1  | alice            | merged          | 2 h          | 10+5 = 15 (two files)
  2  | dependabot[bot]  | merged          | 4 h          | 3+1 = 4
  3  | bob              | closed, no merge| 10 h         | 0 (no files)
  4  | carol            | open            | -            | 100
  """
  repository = add_repository(db_session)

  pr1 = add_pull_request(db_session, repository, 1, author="alice", merged=True)
  close_after(db_session, pr1, 2)
  add_file(db_session, pr1, "app/a.py", 8, 4)
  add_file(db_session, pr1, "app/b.py", 2, 1)

  pr2 = add_pull_request(db_session, repository, 2, author="dependabot[bot]", merged=True)
  close_after(db_session, pr2, 4)
  add_file(db_session, pr2, "requirements.txt", 3, 1)

  pr3 = add_pull_request(db_session, repository, 3, author="bob")
  close_after(db_session, pr3, 10)

  pr4 = add_pull_request(db_session, repository, 4, author="carol", status="open")
  add_file(db_session, pr4, "app/big.py", 100, 0)

  return repository


def get_stats(client, repository_id):
  response = client.get(f"/repositories/{repository_id}/stats")
  assert response.status_code == 200
  return response.json()


def test_counts(client, repository):
  stats = get_stats(client, repository.id)

  assert stats["repository_id"] == repository.id
  assert stats["total_prs"] == 4
  assert stats["closed_prs"] == 3
  assert stats["merged_prs"] == 2
  assert stats["bot_prs"] == 1


def test_merge_rate_divides_by_closed_not_total(client, repository):
  stats = get_stats(client, repository.id)

  # 2 merged / 3 closed. The open PR is not decided yet, so it is not counted.
  assert stats["merge_rate"] == pytest.approx(2 / 3)


def test_bot_share_divides_by_total(client, repository):
  assert get_stats(client, repository.id)["bot_share"] == pytest.approx(0.25)


def test_median_lines_interpolates_and_counts_prs_without_files(client, repository):
  # Lines per PR: 0, 4, 15, 100. Even count, so the median is (4 + 15) / 2.
  # If the 0-file PR were dropped, the median would be 15 instead.
  assert get_stats(client, repository.id)["median_lines_changed"] == pytest.approx(9.5)


def test_median_hours_ignores_open_prs(client, repository):
  # Closed PRs took 2, 4 and 10 hours; the open PR has no close time.
  assert get_stats(client, repository.id)["median_hours_to_close"] == pytest.approx(4.0)


def test_only_counts_this_repositorys_pull_requests(client, db_session, repository):
  other = add_repository(db_session, number=2)
  other_pr = add_pull_request(db_session, other, 99, merged=True)
  add_file(db_session, other_pr, "x.py", 1000, 0)

  stats = get_stats(client, repository.id)

  assert stats["total_prs"] == 4
  assert stats["median_lines_changed"] == pytest.approx(9.5)


def test_repository_without_pull_requests_returns_nulls(client, db_session):
  repository = add_repository(db_session)

  stats = get_stats(client, repository.id)

  assert stats["total_prs"] == 0
  assert stats["closed_prs"] == 0
  assert stats["merge_rate"] is None
  assert stats["bot_share"] is None
  assert stats["median_lines_changed"] is None
  assert stats["median_hours_to_close"] is None


def test_only_open_pull_requests_has_no_merge_rate(client, db_session):
  repository = add_repository(db_session)
  add_pull_request(db_session, repository, 1, status="open")

  stats = get_stats(client, repository.id)

  assert stats["total_prs"] == 1
  assert stats["merge_rate"] is None
  assert stats["median_hours_to_close"] is None
  assert stats["median_lines_changed"] == pytest.approx(0.0)


def test_unknown_repository_is_404(client):
  assert client.get("/repositories/999/stats").status_code == 404
