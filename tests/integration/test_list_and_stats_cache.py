import pytest

from tests.integration.test_pull_request_detail import count_queries
from tests.integration.test_pull_requests_api import add_pull_request, add_repository


@pytest.fixture
def repository(db_session):
  repository = add_repository(db_session)
  add_pull_request(db_session, repository, 1, status="open", day=1)
  add_pull_request(db_session, repository, 2, status="closed", day=2)
  add_pull_request(db_session, repository, 3, status="open", day=3)
  return repository


def numbers(response):
  return [item["number"] for item in response.json()["items"]]


def list_keys(redis_client, repository):
  return redis_client.keys(f"pull_requests:{repository.id}:*")


# ---------- PR list ----------

def test_list_second_call_runs_no_queries(client, engine, repository):
  url = f"/repositories/{repository.id}/pull-requests"

  with count_queries(engine) as first:
    first_response = client.get(url)
  with count_queries(engine) as second:
    second_response = client.get(url)

  assert len(first) > 0
  assert len(second) == 0
  assert second_response.json() == first_response.json()
  assert second_response.headers["content-type"] == "application/json"


def test_different_filters_get_different_entries(client, redis_client, repository):
  url = f"/repositories/{repository.id}/pull-requests"

  assert numbers(client.get(url, params={"status": "open"})) == [3, 1]
  assert numbers(client.get(url, params={"status": "closed"})) == [2]
  assert numbers(client.get(url, params={"status": "open"})) == [3, 1]
  assert len(list_keys(redis_client, repository)) == 2


def test_pages_do_not_mix(client, redis_client, repository):
  url = f"/repositories/{repository.id}/pull-requests"

  first_page = client.get(url, params={"limit": 2}).json()
  second_page = client.get(url, params={"limit": 2, "cursor": first_page["next_cursor"]})
  first_page_again = client.get(url, params={"limit": 2}).json()

  assert [item["number"] for item in first_page["items"]] == [3, 2]
  assert numbers(second_page) == [1]
  assert first_page_again == first_page
  assert len(list_keys(redis_client, repository)) == 2


def test_limit_is_part_of_the_key(client, repository):
  url = f"/repositories/{repository.id}/pull-requests"

  assert len(client.get(url, params={"limit": 1}).json()["items"]) == 1
  assert len(client.get(url, params={"limit": 3}).json()["items"]) == 3


def test_same_moment_in_different_formats_shares_one_entry(client, redis_client, repository):
  url = f"/repositories/{repository.id}/pull-requests"

  client.get(url, params={"created_after": "2026-01-02T00:00:00Z"})
  client.get(url, params={"created_after": "2026-01-02T00:00:00+00:00"})

  assert len(list_keys(redis_client, repository)) == 1


def test_unknown_query_parameters_do_not_create_entries(client, redis_client, repository):
  url = f"/repositories/{repository.id}/pull-requests"

  client.get(url)
  client.get(url, params={"utm_source": "newsletter"})

  assert len(list_keys(redis_client, repository)) == 1


def test_list_errors_are_not_cached(client, redis_client, repository):
  assert client.get("/repositories/999/pull-requests").status_code == 404
  bad_cursor = client.get(
    f"/repositories/{repository.id}/pull-requests", params={"cursor": "nonsense"}
  )
  assert bad_cursor.status_code == 400
  assert redis_client.keys() == []


# ---------- Repository stats ----------

def test_stats_second_call_runs_no_queries(client, engine, redis_client, repository):
  url = f"/repositories/{repository.id}/stats"

  with count_queries(engine) as first:
    first_response = client.get(url)
  with count_queries(engine) as second:
    second_response = client.get(url)

  assert len(first) > 0
  assert len(second) == 0
  assert second_response.json() == first_response.json()
  assert 0 < redis_client.ttl(f"repository_stats:{repository.id}") <= 300


def test_stats_are_cached_per_repository(client, db_session, repository):
  other = add_repository(db_session, number=2)
  add_pull_request(db_session, other, 99)

  assert client.get(f"/repositories/{repository.id}/stats").json()["total_prs"] == 3
  assert client.get(f"/repositories/{other.id}/stats").json()["total_prs"] == 1


def test_stats_404_is_not_cached(client, redis_client):
  assert client.get("/repositories/999/stats").status_code == 404
  assert redis_client.keys() == []
