import hashlib
import hmac
import json

from sqlalchemy import func, select

from app.core.config import settings
from app.db.models import GitHubEvent, JobRun, PullRequest, PullRequestFile, Repository

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


def test_ping_event_is_stored_and_queued(client, db_session, fake_broker):
  response = send_webhook(client, "d-1", "ping", {"zen": "hi"})

  assert response.status_code == 202
  assert response.json()["status"] == "queued"
  event = get_event(db_session, "d-1")
  assert event.status == "received"
  job = db_session.scalars(select(JobRun)).one()
  assert (job.job_type, job.status, job.event_id, job.payload) == (
    "process_event", "queued", event.id, {"event_id": event.id}
  )
  assert fake_broker.jobs == [("process_event", job.id)]


def test_webhook_only_stores_and_queues(client, db_session, fake_github, fake_broker):
  """The request does no processing: no GitHub call, no PR rows until the worker runs."""
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}

  response = send_webhook(client, "d-1", "pull_request", payload)

  assert response.status_code == 202
  assert count(db_session, GitHubEvent) == 1
  assert count(db_session, PullRequest) == 0
  assert fake_github.calls == []
  assert len(fake_broker.job_ids("process_event")) == 1


def test_worker_stores_repo_pr_and_files(client, db_session, fake_github, worker):
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}
  send_webhook(client, "d-1", "pull_request", payload)

  worker.run()

  assert worker.failures == []
  assert count(db_session, Repository) == 1
  assert count(db_session, PullRequest) == 1
  assert count(db_session, PullRequestFile) == 2
  assert fake_github.calls == [("octo/demo", 7)]
  event = get_event(db_session, "d-1")
  assert event.status == "processed"
  assert event.processed_at is not None


def test_duplicate_delivery_is_not_queued_again(client, db_session, fake_broker):
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}
  send_webhook(client, "d-1", "pull_request", payload)

  response = send_webhook(client, "d-1", "pull_request", payload)

  assert response.status_code == 200
  assert response.json()["status"] == "duplicate_ignored"
  assert count(db_session, GitHubEvent) == 1
  assert len(fake_broker.jobs) == 1


def test_new_commit_updates_pr_and_replaces_files(client, db_session, fake_github, worker):
  send_webhook(client, "d-1", "pull_request",
               {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()})
  worker.run()

  fake_github.files = fake_github.files[:1]  # the new commit leaves only one changed file
  send_webhook(client, "d-2", "pull_request",
               {"action": "synchronize", "repository": repo_payload(),
                "pull_request": pr_payload(title="Add feature v2", head_sha="c" * 40)})
  worker.run()

  assert count(db_session, PullRequest) == 1  # updated, not duplicated
  pr = db_session.execute(select(PullRequest)).scalar_one()
  assert pr.title == "Add feature v2"
  assert pr.head_sha == "c" * 40
  assert count(db_session, PullRequestFile) == 1


def test_github_failure_fails_only_the_file_sync(client, db_session, fake_github, worker):
  """The PR row is saved by process_event; only the GitHub part fails (retries come later)."""
  fake_github.should_fail = True
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}

  response = send_webhook(client, "d-1", "pull_request", payload)
  worker.run()

  assert response.status_code == 202  # GitHub's outage is not our webhook's outage
  assert get_event(db_session, "d-1").status == "processed"
  assert count(db_session, PullRequest) == 1
  assert count(db_session, PullRequestFile) == 0
  assert len(worker.failures) == 1
  assert "503" in str(worker.failures[0])


def test_enqueue_failure_marks_event_failed_and_returns_503(client, db_session, fake_broker):
  fake_broker.should_fail = True
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}

  response = send_webhook(client, "d-1", "pull_request", payload)

  assert response.status_code == 503
  assert response.json()["error"]["code"] == "service_unavailable"
  event = get_event(db_session, "d-1")
  assert event.status == "failed"
  assert "Redis is unreachable" in event.error_message
  job = db_session.scalars(select(JobRun)).one()
  assert job.status == "failed"  # the job row is a dead letter too, never stuck in "queued"


def test_failed_delivery_is_queued_again_when_redelivered(client, db_session, fake_broker, worker):
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}
  fake_broker.should_fail = True
  send_webhook(client, "d-1", "pull_request", payload)

  fake_broker.should_fail = False
  response = send_webhook(client, "d-1", "pull_request", payload)
  worker.run()

  assert response.status_code == 202
  db_session.expire_all()  # forget cached values, read fresh from the database
  event = get_event(db_session, "d-1")
  assert event.status == "processed"
  assert event.error_message is None
  assert count(db_session, PullRequestFile) == 2


def test_event_and_job_are_committed_before_dispatch(client, engine, monkeypatch):
  """The worker uses its own connection, so the rows must already be visible to others."""
  from sqlalchemy.orm import Session

  import app.jobs as jobs

  seen_by_worker = []

  def check_from_another_connection(task, job_id):
    with Session(engine) as other:
      job = other.get(JobRun, job_id)
      seen_by_worker.append(job is not None and other.get(GitHubEvent, job.event_id) is not None)

  monkeypatch.setattr(jobs, "dispatch", check_from_another_connection)

  send_webhook(client, "d-1", "ping", {"zen": "hi"})

  assert seen_by_worker == [True]
