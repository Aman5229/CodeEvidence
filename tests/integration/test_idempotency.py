"""At-least-once delivery means a job can run twice. Running it twice must change nothing."""

from sqlalchemy import select

import app.modules.ingestion.service as service
from app.db.models import GitHubEvent, PullRequest, PullRequestFile
from tests.integration.test_github_webhook import pr_payload, repo_payload, send_webhook


def pr_event(**changes) -> dict:
  pull_request = pr_payload()
  pull_request.update(changes)
  return {"action": "edited", "repository": repo_payload(), "pull_request": pull_request}


def snapshot(db_session) -> dict:
  db_session.expire_all()
  pr = db_session.scalars(select(PullRequest)).one()
  event = db_session.scalars(select(GitHubEvent)).one()
  files = db_session.scalars(select(PullRequestFile.path).order_by(PullRequestFile.path)).all()
  return {
    "pr": (pr.id, pr.title, pr.status, pr.head_sha, pr.updated_at),
    "files": files,
    "event": (event.status, event.processed_at, event.error_message),
  }


def test_running_the_same_jobs_twice_changes_nothing(client, db_session, fake_broker, worker,
                                                     fake_github):
  send_webhook(client, "d-1", "pull_request", pr_event())
  process_job_id = fake_broker.job_ids("process_event")[0]
  worker.run()
  first = snapshot(db_session)

  fake_broker.jobs.append(("process_event", process_job_id))  # Redis hands it out again
  worker.run()

  assert worker.failures == []
  assert snapshot(db_session) == first  # same rows, same files, same processed_at
  assert len(fake_github.calls) == 2  # the file sync was queued and run again, not skipped


def test_older_event_processed_late_does_not_overwrite_newer_data(client, db_session,
                                                                  worker):
  """Two worker processes can finish events out of order; the newest data must win."""
  newer = pr_event(title="v2", updated_at="2024-06-01T10:00:01Z")
  older = pr_event(title="v1", updated_at="2024-06-01T10:00:00Z")

  send_webhook(client, "d-newer", "pull_request", newer)
  send_webhook(client, "d-older", "pull_request", older)
  worker.run()  # processes the newer event first, then the older one

  pr = db_session.scalars(select(PullRequest)).one()
  assert pr.title == "v2"


def test_same_update_processed_again_is_applied(client, db_session, worker):
  """Equal timestamps mean the same version: writing it again is harmless."""
  send_webhook(client, "d-1", "pull_request", pr_event(title="v1"))
  worker.run()
  send_webhook(client, "d-2", "pull_request", pr_event(title="v1 again"))
  worker.run()

  assert db_session.scalars(select(PullRequest.title)).one() == "v1 again"


def test_same_delivery_arriving_twice_at_once_is_stored_once(client, db_session, monkeypatch):
  """Both requests pass the duplicate check; the unique constraint decides the winner."""
  monkeypatch.setattr(service, "get_event_by_delivery_id", lambda db, delivery_id: None)

  first = send_webhook(client, "d-1", "pull_request", pr_event())
  second = send_webhook(client, "d-1", "pull_request", pr_event())

  assert first.status_code == 202
  assert second.status_code == 200
  assert second.json()["status"] == "duplicate_ignored"
  assert len(db_session.scalars(select(GitHubEvent)).all()) == 1
