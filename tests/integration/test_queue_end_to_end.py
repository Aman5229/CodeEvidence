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
  everything = db_session.scalars(select(JobRun)).all()
  states = sorted((job.job_type, job.status, job.attempts, job.last_error) for job in everything)
  raise AssertionError(f"jobs did not finish within {timeout}s: {states}")


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


def test_no_event_is_lost_when_30_percent_of_github_calls_fail(client, db_session, fake_github,
                                                               redis_client, monkeypatch,
                                                               real_queue):
  """Fault injection (M5): a fake GitHub fails 30% of calls at random. Retries must still get
  every PR's files stored, with no job left failed. (Random failures rarely come 5 in a row,
  so the circuit breaker stays closed here; the outage test below covers it.)"""
  from app.integrations.github.guard import GitHubGuard

  # Real breaker, short open period so the test stays quick.
  monkeypatch.setattr(jobs, "get_github_guard", lambda: GitHubGuard(redis_client, open_seconds=1))
  fake_github.failure_rate = 0.30
  events = 40

  for number in range(1, events + 1):
    pull_request = pr_payload()
    pull_request.update(id=10_000 + number, number=number)
    payload = {"action": "opened", "repository": repo_payload(), "pull_request": pull_request}
    assert send_webhook(client, f"d-{number}", "pull_request", payload).status_code == 202

  finished = wait_until_jobs_finish(db_session, expected=2 * events, timeout=90)

  assert [job.status for job in finished].count("succeeded") == 2 * events  # nothing failed
  files = db_session.scalars(select(PullRequestFile)).all()
  assert len({file.pull_request_id for file in files}) == events  # every PR got its files
  failed_calls = len(fake_github.calls) - events
  assert failed_calls > 0  # faults really happened
  print(f"\n{events} events: {len(fake_github.calls)} GitHub calls, {failed_calls} failed and were retried")


def test_circuit_opens_during_an_outage_and_recovers(client, db_session, fake_github,
                                                     redis_client, monkeypatch, real_queue):
  """GitHub is down for its first 12 calls, then healthy. The breaker must stop the calls
  while it is down (runs are paused, not sent), and every event must still complete."""
  from app.integrations.github.guard import GitHubGuard

  monkeypatch.setattr(jobs, "get_github_guard", lambda: GitHubGuard(redis_client, open_seconds=1))
  fake_github.fail_times = 12
  events = 20

  for number in range(1, events + 1):
    pull_request = pr_payload()
    pull_request.update(id=20_000 + number, number=number)
    payload = {"action": "opened", "repository": repo_payload(), "pull_request": pull_request}
    send_webhook(client, f"d-{number}", "pull_request", payload)

  finished = wait_until_jobs_finish(db_session, expected=2 * events, timeout=90)

  assert [job.status for job in finished].count("succeeded") == 2 * events
  sync_runs = sum(job.attempts for job in finished if job.job_type == "sync_pr_files")
  paused_runs = sync_runs - len(fake_github.calls)  # runs the open circuit stopped before calling
  assert paused_runs > 0
  assert len(fake_github.calls) < 12 + events + paused_runs  # the breaker saved calls
  print(f"\n{events} events: {len(fake_github.calls)} GitHub calls, "
        f"{paused_runs} runs paused by the open circuit instead of calling a failing GitHub")
