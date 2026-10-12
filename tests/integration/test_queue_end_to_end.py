"""The whole path with the real queue: webhook -> Redis -> Celery worker -> database.

Unlike the other tests, nothing here is faked except GitHub. A Celery worker runs in a
thread of the test process, against its own Redis database (TEST_CELERY_BROKER_URL).
"""

import os
import time

import pytest
from celery.contrib.testing.worker import start_worker
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.jobs as jobs
from app.db.models import JobRun, PullRequestFile
from app.worker import celery_app
from tests.integration.test_github_webhook import pr_payload, repo_payload, send_webhook

TEST_BROKER_URL = os.getenv("TEST_CELERY_BROKER_URL", "redis://localhost:6380/14")
REAL_DISPATCH = jobs.dispatch  # saved before any test replaces it with the fake broker


@pytest.fixture
def real_queue(monkeypatch, engine, redis_client, fake_github):
  Redis.from_url(TEST_BROKER_URL).flushdb()  # no jobs left over from earlier runs
  monkeypatch.setattr(jobs, "dispatch", REAL_DISPATCH)
  monkeypatch.setattr(jobs, "SessionLocal", sessionmaker(bind=engine))  # the test database
  monkeypatch.setattr(jobs, "redis_client", redis_client)
  monkeypatch.setattr(jobs, "get_github_client", lambda: fake_github)
  monkeypatch.setattr(jobs, "retry_delay_seconds", lambda attempt: 0)  # retry at once
  monkeypatch.setattr(celery_app.conf, "broker_url", TEST_BROKER_URL)

  with start_worker(celery_app, pool="solo", perform_ping_check=False, shutdown_timeout=10):
    yield


def wait_until_jobs_finish(db_session, expected: int, timeout: float = 15) -> list[JobRun]:
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    db_session.expire_all()
    jobs_done = db_session.scalars(
      select(JobRun).where(JobRun.status.in_(["succeeded", "failed"])).order_by(JobRun.id)
    ).all()
    if len(jobs_done) >= expected:
      return jobs_done
    time.sleep(0.1)
  raise AssertionError(f"jobs did not finish within {timeout}s")


def test_webhook_to_worker_to_database(client, db_session, real_queue):
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}

  assert send_webhook(client, "d-1", "pull_request", payload).status_code == 202

  finished = wait_until_jobs_finish(db_session, expected=2)
  assert [(job.job_type, job.status) for job in finished] == [
    ("process_event", "succeeded"),
    ("sync_pr_files", "succeeded"),
  ]
  assert len(db_session.scalars(select(PullRequestFile)).all()) == 2


def test_a_transient_failure_is_retried_through_redis(client, db_session, fake_github,
                                                      real_queue):
  fake_github.fail_times = 1  # one 503, then success
  payload = {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}

  send_webhook(client, "d-1", "pull_request", payload)

  finished = wait_until_jobs_finish(db_session, expected=2)
  sync = finished[-1]
  assert (sync.job_type, sync.status, sync.attempts) == ("sync_pr_files", "succeeded", 2)
  assert len(fake_github.calls) == 2
