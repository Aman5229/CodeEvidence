import pytest

from tests.integration.test_pull_request_detail import add_files, count_queries
from tests.integration.test_pull_requests_api import add_pull_request, add_repository


@pytest.fixture
def pull_request(db_session):
  repository = add_repository(db_session)
  pull_request = add_pull_request(db_session, repository, 1)
  add_files(db_session, pull_request, 2)
  return pull_request


def test_second_call_is_served_from_cache(client, engine, pull_request):
  url = f"/pull-requests/{pull_request.id}"

  with count_queries(engine) as first:
    first_response = client.get(url)
  with count_queries(engine) as second:
    second_response = client.get(url)

  assert len(first) == 2
  assert len(second) == 0
  assert second_response.status_code == 200
  assert second_response.headers["content-type"] == "application/json"
  assert second_response.json() == first_response.json()


def test_patch_variants_use_separate_keys(client, redis_client, pull_request):
  url = f"/pull-requests/{pull_request.id}"

  with_patch = client.get(url, params={"include_patch": "true"}).json()
  without_patch = client.get(url).json()

  assert "patch" in with_patch["files"][0]
  assert "patch" not in without_patch["files"][0]
  assert sorted(redis_client.keys()) == [
    f"pull_request:{pull_request.id}:patch=0",
    f"pull_request:{pull_request.id}:patch=1",
  ]


def test_cached_entry_has_ttl(client, redis_client, pull_request):
  client.get(f"/pull-requests/{pull_request.id}")

  assert 0 < redis_client.ttl(f"pull_request:{pull_request.id}:patch=0") <= 300


def test_not_found_is_not_cached(client, redis_client):
  assert client.get("/pull-requests/999").status_code == 404
  assert redis_client.keys() == []


def test_database_change_is_not_seen_until_the_entry_expires(
  client, db_session, redis_client, pull_request
):
  """Known trade-off until webhook invalidation exists: reads can be stale for up to the TTL."""
  url = f"/pull-requests/{pull_request.id}"
  client.get(url)

  pull_request.title = "Renamed"
  db_session.commit()

  assert client.get(url).json()["title"] == "PR 1"

  redis_client.delete(f"pull_request:{pull_request.id}:patch=0")
  assert client.get(url).json()["title"] == "Renamed"
