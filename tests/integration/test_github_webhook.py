import hashlib
import hmac
import json

from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import GitHubEvent, PullRequest, PullRequestFile, Repository


# ---------- helpers ----------

def repo_payload(repo_id: int = 1001) -> dict:
  return {
    "id": repo_id,
    "full_name": "octo/demo",
    "owner": {"login": "octo"},
    "default_branch": "main",
    "html_url": "https://github.com/octo/demo",
    "private": False,
    "created_at": "2024-01-01T12:00:00Z",
    "updated_at": "2024-06-01T09:30:00Z",
  }


def pr_payload(title: str = "Add feature", head_sha: str = "b" * 40) -> dict:
  return {
    "id": 2001,
    "number": 7,
    "title": title,
    "body": None,
    "state": "open",
    "user": {"id": 3001, "login": "octo"},
    "base": {"ref": "main", "sha": "a" * 40},
    "head": {"ref": "feature", "sha": head_sha},
    "created_at": "2024-06-01T09:00:00Z",
    "updated_at": "2024-06-01T09:30:00Z",
    "closed_at": None,
    "merged_at": None,
  }


def send_webhook(client, delivery_id: str, event_type: str, payload: dict, signature: str | None = None):
  body = json.dumps(payload).encode("utf-8")
  if signature is None:
    digest = hmac.new(settings.github_webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    signature = "sha256=" + digest
  headers = {
    "X-GitHub-Delivery": delivery_id,
    "X-GitHub-Event": event_type,
    "X-Hub-Signature-256": signature,
    "Content-Type": "application/json",
  }
  return client.post("/webhooks/github", content=body, headers=headers)


def count(db_session, model) -> int:
  return db_session.execute(select(func.count()).select_from(model)).scalar_one()


def get_event(db_session, delivery_id: str) -> GitHubEvent:
  return db_session.execute(
    select(GitHubEvent).where(GitHubEvent.github_delivery_id == delivery_id)
  ).scalar_one()


# ---------- tests ----------

def test_invalid_signature_is_rejected_and_nothing_is_stored(client, db_session):
  response = send_webhook(client, "d-1", "ping", {"zen": "hi"}, signature="sha256=wrong")

  assert response.status_code == 401
  assert count(db_session, GitHubEvent) == 0


def test_ping_event_is_stored_as_received(client, db_session):
  response = send_webhook(client, "d-1", "ping", {"zen": "hi"})

  assert response.status_code == 200
  event = get_event(db_session, "d-1")
  assert event.status == "received"
  assert event.repository_id is None


def test_pull_request_event_stores_repo_pr_and_files(client, db_session, fake_github):
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}

  response = send_webhook(client, "d-1", "pull_request", payload)

  assert response.status_code == 200
  assert count(db_session, Repository) == 1
  assert count(db_session, PullRequest) == 1
  assert count(db_session, PullRequestFile) == 2
  assert fake_github.calls == [("octo/demo", 7)]

  event = get_event(db_session, "d-1")
  assert event.status == "processed"
  assert event.processed_at is not None


def test_duplicate_delivery_is_ignored(client, db_session, fake_github):
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}
  send_webhook(client, "d-1", "pull_request", payload)

  response = send_webhook(client, "d-1", "pull_request", payload)

  assert response.json()["status"] == "duplicate_ignored"
  assert count(db_session, GitHubEvent) == 1
  assert len(fake_github.calls) == 1  # GitHub was NOT called a second time


def test_new_commit_updates_pr_and_replaces_files(client, db_session, fake_github):
  send_webhook(client, "d-1", "pull_request",
               {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()})

  fake_github.files = fake_github.files[:1]  # the new commit leaves only one changed file
  send_webhook(client, "d-2", "pull_request",
               {"action": "synchronize", "repository": repo_payload(),
                "pull_request": pr_payload(title="Add feature v2", head_sha="c" * 40)})

  assert count(db_session, PullRequest) == 1  # updated, not duplicated
  pr = db_session.execute(select(PullRequest)).scalar_one()
  assert pr.title == "Add feature v2"
  assert pr.head_sha == "c" * 40
  assert count(db_session, PullRequestFile) == 1


def test_github_failure_keeps_event_and_rolls_back_everything_else(client, db_session, fake_github):
  fake_github.should_fail = True
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}

  response = send_webhook(client, "d-1", "pull_request", payload)

  assert response.status_code == 500
  event = get_event(db_session, "d-1")
  assert event.status == "failed"
  assert "503" in event.error_message
  assert count(db_session, Repository) == 0
  assert count(db_session, PullRequest) == 0
  assert count(db_session, PullRequestFile) == 0


def test_failed_delivery_is_processed_when_redelivered(client, db_session, fake_github):
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}
  fake_github.should_fail = True
  send_webhook(client, "d-1", "pull_request", payload)

  fake_github.should_fail = False
  response = send_webhook(client, "d-1", "pull_request", payload)

  assert response.status_code == 200
  db_session.expire_all()  # forget cached values, read fresh from the database
  event = get_event(db_session, "d-1")
  assert event.status == "processed"
  assert event.error_message is None
  assert count(db_session, PullRequestFile) == 2
