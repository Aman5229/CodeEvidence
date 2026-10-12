"""When the worker processes a PR event, it deletes every cached response containing that PR."""

import pytest

from tests.integration.test_github_webhook import pr_payload, repo_payload, send_webhook


def pr_event(action: str, **changes) -> dict:
  pull_request = pr_payload()
  pull_request.update(changes)
  return {"action": action, "repository": repo_payload(), "pull_request": pull_request}


def deliver(client, worker, delivery_id: str, payload: dict, event_type="pull_request") -> None:
  """GitHub sends the webhook, then the worker processes what it queued."""
  assert send_webhook(client, delivery_id, event_type, payload).status_code == 202
  worker.run()


@pytest.fixture
def stored(client, worker):
  """One repo with one PR, received by webhook. Returns (repository_id, pull_request_id)."""
  deliver(client, worker, "d-open", pr_event("opened"))
  repository_id = client.get("/repositories").json()["items"][0]["id"]
  pr_list = client.get(f"/repositories/{repository_id}/pull-requests").json()
  return repository_id, pr_list["items"][0]["id"]


def warm_cache(client, repository_id: int, pull_request_id: int) -> None:
  client.get(f"/pull-requests/{pull_request_id}")
  client.get(f"/pull-requests/{pull_request_id}", params={"include_patch": "true"})
  client.get(f"/repositories/{repository_id}/pull-requests")
  client.get(f"/repositories/{repository_id}/stats")


def test_update_then_read_shows_fresh_data(client, worker, stored):
  repository_id, pull_request_id = stored
  warm_cache(client, repository_id, pull_request_id)

  event = pr_event("closed", title="Renamed", state="closed", closed_at="2024-06-02T09:00:00Z")
  deliver(client, worker, "d-close", event)

  assert client.get(f"/pull-requests/{pull_request_id}").json()["title"] == "Renamed"
  patched = client.get(f"/pull-requests/{pull_request_id}", params={"include_patch": "true"})
  assert patched.json()["status"] == "closed"
  pr_list = client.get(f"/repositories/{repository_id}/pull-requests").json()
  assert pr_list["items"][0]["title"] == "Renamed"
  assert client.get(f"/repositories/{repository_id}/stats").json()["closed_prs"] == 1


def test_new_pull_request_appears_in_cached_list_and_stats(client, worker, stored):
  repository_id, pull_request_id = stored
  warm_cache(client, repository_id, pull_request_id)

  deliver(client, worker, "d-open-2",
          pr_event("opened", id=2002, number=8, created_at="2024-06-03T09:00:00Z"))

  pr_list = client.get(f"/repositories/{repository_id}/pull-requests").json()
  assert [item["number"] for item in pr_list["items"]] == [8, 7]
  assert client.get(f"/repositories/{repository_id}/stats").json()["total_prs"] == 2


def test_other_repositories_keep_their_cache(client, worker, redis_client, stored):
  redis_client.set("pull_requests:999:abc", "x")
  redis_client.set("repository_stats:999", "x")
  redis_client.set("pull_request:999:patch=0", "x")

  deliver(client, worker, "d-edit", pr_event("edited", title="New"))

  assert redis_client.get("pull_requests:999:abc") == "x"
  assert redis_client.get("repository_stats:999") == "x"
  assert redis_client.get("pull_request:999:patch=0") == "x"


def test_file_sync_failure_still_shows_the_pr_update(client, worker, fake_github, stored):
  """process_event saves and invalidates the PR change; only the GitHub file sync fails."""
  repository_id, pull_request_id = stored
  warm_cache(client, repository_id, pull_request_id)

  fake_github.should_fail = True
  deliver(client, worker, "d-edit", pr_event("edited", title="Renamed"))

  assert len(worker.failures) == 1
  detail = client.get(f"/pull-requests/{pull_request_id}").json()
  assert detail["title"] == "Renamed"
  assert len(detail["files"]) == 2  # the old files stay until a sync succeeds


def test_non_pull_request_event_deletes_nothing(client, worker, redis_client, stored):
  repository_id, pull_request_id = stored
  warm_cache(client, repository_id, pull_request_id)
  keys_before = sorted(redis_client.keys())

  deliver(client, worker, "d-ping", {"zen": "hi", "repository": repo_payload()}, "ping")

  assert sorted(redis_client.keys()) == keys_before
