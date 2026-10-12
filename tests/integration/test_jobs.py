"""Background jobs: payloads, the service functions they call, and the job wrappers."""

import asyncio
from contextlib import nullcontext

import pytest
from pydantic import ValidationError
from sqlalchemy import select

import app.jobs as jobs
from app.db.models import PullRequest, PullRequestFile
from app.modules.ingestion.event_store import record_event
from app.modules.ingestion.service import process_stored_event, sync_files_for_pull_request
from app.schemas.jobs import ProcessEventPayload, SyncPullRequestFilesPayload
from tests.integration.test_github_webhook import pr_payload, repo_payload


def store_event(db_session, event_type="pull_request", payload=None, delivery_id="d-1"):
  if payload is None:
    payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}
  event = record_event(
    db_session,
    delivery_id=delivery_id,
    event_type=event_type,
    action=payload.get("action"),
    payload=payload,
  )
  db_session.commit()
  return event


# ---------- payloads ----------

def test_payloads_accept_ids():
  assert ProcessEventPayload.model_validate({"event_id": 7}).event_id == 7
  assert SyncPullRequestFilesPayload.model_validate({"pull_request_id": 9}).pull_request_id == 9


@pytest.mark.parametrize("payload", [{}, {"event_id": "abc"}, {"event_id": None}])
def test_bad_payloads_are_rejected(payload):
  with pytest.raises(ValidationError):
    ProcessEventPayload.model_validate(payload)


def test_unknown_fields_are_ignored_so_newer_producers_do_not_break_older_workers():
  assert ProcessEventPayload.model_validate({"event_id": 7, "added_later": True}).event_id == 7


# ---------- process_stored_event (database only) ----------

def test_pull_request_event_becomes_repository_and_pr_rows(db_session):
  event = store_event(db_session)

  repository_id, pull_request_id = process_stored_event(db_session, event.id)

  pr = db_session.get(PullRequest, pull_request_id)
  assert pr.repository_id == repository_id
  assert pr.title == "Add feature"
  db_session.refresh(event)
  assert event.status == "processed"
  assert event.repository_id == repository_id
  assert db_session.scalars(select(PullRequestFile)).all() == []  # files come in the next job


def test_non_pull_request_event_is_marked_received(db_session):
  event = store_event(db_session, "ping", {"zen": "hi", "repository": repo_payload()})

  repository_id, pull_request_id = process_stored_event(db_session, event.id)

  assert repository_id is not None
  assert pull_request_id is None
  db_session.refresh(event)
  assert event.status == "received"


def test_failure_marks_the_event_failed_and_reraises(db_session):
  broken = pr_payload()
  del broken["title"]
  event = store_event(
    db_session, payload={"action": "opened", "repository": repo_payload(), "pull_request": broken}
  )

  with pytest.raises(KeyError):
    process_stored_event(db_session, event.id)

  db_session.refresh(event)
  assert event.status == "failed"
  assert "title" in event.error_message
  assert db_session.scalars(select(PullRequest)).all() == []  # nothing half-written


def test_missing_event_fails_loudly(db_session):
  with pytest.raises(ValueError, match="does not exist"):
    process_stored_event(db_session, 999)


# ---------- sync_files_for_pull_request (GitHub + database) ----------

def test_files_are_fetched_and_stored(db_session, fake_github):
  repository_id, pull_request_id = process_stored_event(db_session, store_event(db_session).id)

  stored_in = asyncio.run(sync_files_for_pull_request(db_session, fake_github, pull_request_id))

  assert stored_in == repository_id
  paths = db_session.scalars(select(PullRequestFile.path).order_by(PullRequestFile.path)).all()
  assert paths == ["app/main.py", "app/new_feature.py"]


def test_missing_pull_request_fails_loudly(db_session, fake_github):
  with pytest.raises(ValueError, match="does not exist"):
    asyncio.run(sync_files_for_pull_request(db_session, fake_github, 999))


# ---------- the job wrappers ----------

@pytest.fixture
def wired_jobs(monkeypatch, db_session, redis_client, fake_github):
  """Run the jobs against the test DB, test Redis and fake GitHub; record enqueued jobs."""
  queued = []
  monkeypatch.setattr(jobs, "SessionLocal", lambda: nullcontext(db_session))
  monkeypatch.setattr(jobs, "redis_client", redis_client)
  monkeypatch.setattr(jobs, "get_github_client", lambda: fake_github)
  monkeypatch.setattr(jobs, "enqueue_sync_pr_files", queued.append)
  return queued


def test_process_event_job_queues_the_file_sync(wired_jobs, db_session, redis_client):
  event = store_event(db_session)
  redis_client.set("pull_request:1:patch=0", "stale")

  jobs.process_event({"event_id": event.id})  # calling a task directly runs it now

  pull_request_id = db_session.scalars(select(PullRequest.id)).one()
  assert wired_jobs == [pull_request_id]
  assert redis_client.get("pull_request:1:patch=0") is None  # cache invalidated


def test_sync_pr_files_job_stores_files(wired_jobs, db_session):
  _, pull_request_id = process_stored_event(db_session, store_event(db_session).id)

  jobs.sync_pr_files({"pull_request_id": pull_request_id})

  assert len(db_session.scalars(select(PullRequestFile)).all()) == 2
