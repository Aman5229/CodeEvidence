from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import PullRequest, Repository

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def add_repository(db_session, number: int = 1) -> Repository:
  repository = Repository(
    github_repo_id=1000 + number,
    owner="octo",
    full_name=f"octo/repo{number}",
    default_branch="main",
    html_url=f"https://github.com/octo/repo{number}",
    is_private=False,
    created_at=START,
    updated_at=START,
    ingested_at=START,
    last_synced_at=START,
  )
  db_session.add(repository)
  db_session.commit()
  return repository


def add_pull_request(
  db_session, repository, number, *, author="alice", status="closed", merged=False, day=0
) -> PullRequest:
  created = START + timedelta(days=day)
  pull_request = PullRequest(
    repository_id=repository.id,
    github_pr_id=5000 + number,
    number=number,
    title=f"PR {number}",
    author_login=author,
    base_branch="main",
    head_branch="feature",
    base_sha="a" * 40,
    head_sha="b" * 40,
    status=status,
    created_at=created,
    updated_at=created,
    closed_at=created if status == "closed" else None,
    merged_at=created if merged else None,
    ingested_at=created,
  )
  db_session.add(pull_request)
  db_session.commit()
  return pull_request


@pytest.fixture
def repository(db_session):
  repository = add_repository(db_session)
  add_pull_request(db_session, repository, 1, author="alice", merged=True, day=1)
  add_pull_request(db_session, repository, 2, author="dependabot[bot]", merged=True, day=2)
  add_pull_request(db_session, repository, 3, author="bob", status="open", day=3)
  add_pull_request(db_session, repository, 4, author="renovate[bot]", day=3)
  add_pull_request(db_session, repository, 5, author=None, status="open", day=4)
  return repository


def numbers(response):
  return [item["number"] for item in response.json()["items"]]


def test_lists_newest_first(client, repository):
  response = client.get(f"/repositories/{repository.id}/pull-requests")

  assert response.status_code == 200
  assert numbers(response) == [5, 4, 3, 2, 1]


def test_only_returns_this_repositorys_pull_requests(client, db_session, repository):
  other = add_repository(db_session, number=2)
  add_pull_request(db_session, other, 99)

  response = client.get(f"/repositories/{repository.id}/pull-requests")

  assert 99 not in numbers(response)


def test_filter_by_status(client, repository):
  response = client.get(f"/repositories/{repository.id}/pull-requests?status=open")

  assert numbers(response) == [5, 3]


def test_filter_by_merged(client, repository):
  url = f"/repositories/{repository.id}/pull-requests"

  assert numbers(client.get(url + "?merged=true")) == [2, 1]
  assert numbers(client.get(url + "?merged=false")) == [5, 4, 3]


def test_filter_by_author(client, repository):
  response = client.get(f"/repositories/{repository.id}/pull-requests?author=alice")

  assert numbers(response) == [1]


def test_filter_by_is_bot(client, repository):
  url = f"/repositories/{repository.id}/pull-requests"

  assert numbers(client.get(url + "?is_bot=true")) == [4, 2]
  assert numbers(client.get(url + "?is_bot=false")) == [5, 3, 1]


def test_filter_by_dates(client, repository):
  url = f"/repositories/{repository.id}/pull-requests"

  after = client.get(url, params={"created_after": "2026-01-04T00:00:00Z"})
  before = client.get(url, params={"created_before": "2026-01-04T00:00:00Z"})

  assert numbers(after) == [5, 4, 3]
  assert numbers(before) == [2, 1]


def test_summary_fields_include_computed_flags(client, repository):
  response = client.get(f"/repositories/{repository.id}/pull-requests?author=dependabot[bot]")

  item = response.json()["items"][0]
  assert item["is_bot"] is True
  assert item["is_merged"] is True


def test_paging_across_tied_dates_loses_nothing(client, repository):
  seen = []
  cursor = None
  for _ in range(10):
    params = {"limit": 2}
    if cursor:
      params["cursor"] = cursor
    body = client.get(f"/repositories/{repository.id}/pull-requests", params=params).json()
    seen += [item["number"] for item in body["items"]]
    cursor = body["next_cursor"]
    if cursor is None:
      break

  assert seen == [5, 4, 3, 2, 1]


def test_unknown_repository_is_404(client):
  assert client.get("/repositories/999/pull-requests").status_code == 404


def test_bad_status_is_422(client, repository):
  response = client.get(f"/repositories/{repository.id}/pull-requests?status=weird")

  assert response.status_code == 422


def test_bad_cursor_is_400(client, repository):
  response = client.get(f"/repositories/{repository.id}/pull-requests?cursor=nonsense")

  assert response.status_code == 400