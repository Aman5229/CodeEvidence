"""Background jobs: payloads, the service functions they call, and the job wrappers."""

import asyncio

import pytest
from pydantic import ValidationError
from sqlalchemy import select

import app.jobs as jobs
from app.db.models import JobRun, PullRequest, PullRequestFile
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


# ---------- tracked jobs: status in job_runs ----------

def enqueue(db_session, event_id):
  return jobs.enqueue_process_event(db_session, event_id)


def test_enqueue_records_a_queued_job_and_sends_only_its_id(db_session, fake_broker):
  event = store_event(db_session)

  job = enqueue(db_session, event.id)

  assert (job.job_type, job.status, job.attempts) == ("process_event", "queued", 0)
  assert job.payload == {"event_id": event.id}
  assert fake_broker.jobs == [("process_event", job.id)]


def test_successful_jobs_end_as_succeeded(db_session, fake_broker, worker):
  job = enqueue(db_session, store_event(db_session).id)

  worker.run()

  runs = db_session.scalars(select(JobRun).order_by(JobRun.id)).all()
  assert [(run.job_type, run.status, run.attempts) for run in runs] == [
    ("process_event", "succeeded", 1),
    ("sync_pr_files", "succeeded", 1),  # queued by process_event, linked to the same event
  ]
  assert runs[1].event_id == job.event_id
  assert all(run.finished_at is not None for run in runs)


def test_process_event_clears_the_cached_pr(db_session, fake_broker, worker, redis_client):
  enqueue(db_session, store_event(db_session).id)
  redis_client.set("pull_request:1:patch=0", "stale")

  worker.run()

  assert redis_client.get("pull_request:1:patch=0") is None


def test_non_retryable_failure_is_a_dead_letter_at_once(db_session, fake_broker, worker,
                                                        fake_github):
  fake_github.should_fail = True
  fake_github.status_code = 404  # will fail the same way every time
  enqueue(db_session, store_event(db_session).id)

  worker.run()

  sync = db_session.scalars(select(JobRun).where(JobRun.job_type == "sync_pr_files")).one()
  assert (sync.status, sync.attempts) == ("failed", 1)
  assert "404" in sync.last_error
  assert sync.finished_at is not None


# ---------- retries (T37): eager apply() runs each retry immediately ----------

def sync_job(db_session, fake_broker, worker):
  """A stored PR with a queued sync_pr_files job; returns the job."""
  enqueue(db_session, store_event(db_session).id)
  process_type, process_id = fake_broker.jobs.pop(0)
  jobs.JOB_TASKS[process_type]({"job_id": process_id})
  _, sync_id = fake_broker.jobs.pop(0)
  return db_session.get(JobRun, sync_id)


def test_transient_failures_are_retried_until_success(db_session, fake_broker, worker,
                                                      fake_github):
  job = sync_job(db_session, fake_broker, worker)
  fake_github.fail_times = 2  # 503 twice, then success

  jobs.sync_pr_files.apply(args=[{"job_id": job.id}])

  db_session.refresh(job)
  assert len(fake_github.calls) == 3
  assert (job.status, job.attempts, job.last_error) == ("succeeded", 3, None)
  assert len(db_session.scalars(select(PullRequestFile)).all()) == 2


def test_retries_stop_after_max_retries(db_session, fake_broker, worker, fake_github):
  job = sync_job(db_session, fake_broker, worker)
  fake_github.should_fail = True  # 503 every time

  result = jobs.sync_pr_files.apply(args=[{"job_id": job.id}])

  db_session.refresh(job)
  assert result.failed()
  assert len(fake_github.calls) == 1 + jobs.MAX_RETRIES
  assert (job.status, job.attempts) == ("failed", 1 + jobs.MAX_RETRIES)
  assert "503" in job.last_error


def test_non_retryable_errors_are_not_retried(db_session, fake_broker, worker, fake_github):
  job = sync_job(db_session, fake_broker, worker)
  fake_github.should_fail = True
  fake_github.status_code = 404

  jobs.sync_pr_files.apply(args=[{"job_id": job.id}])

  db_session.refresh(job)
  assert len(fake_github.calls) == 1
  assert (job.status, job.attempts) == ("failed", 1)
