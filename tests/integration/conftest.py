import os
import random

import httpx
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import models  # noqa: F401  (registers all tables on Base.metadata)
from app.db.base import Base
from app.db.redis import get_redis
from app.db.session import get_db
from app.integrations.github.client import get_github_client
from app.main import app

# A SEPARATE database, so tests never touch your real data.
TEST_DATABASE_URL = os.getenv(
  "TEST_DATABASE_URL",
  "postgresql+psycopg://codeevidence:codeevidence@localhost:5433/codeevidence_test",
)

# Database 15 of the compose Redis, so tests never touch the app's cache (db 0).
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6380/15")


class FakeGitHubClient:
  """Stands in for GitHubClient: no network, fully controllable from a test."""

  def __init__(self) -> None:
    self.files = [
      {
        "filename": "app/main.py",
        "status": "modified",
        "additions": 5,
        "deletions": 1,
        "changes": 6,
        "patch": "@@ -1 +1 @@",
        "sha": "abc123",
      },
      {
        "filename": "app/new_feature.py",
        "status": "added",
        "additions": 20,
        "deletions": 0,
        "changes": 20,
        "patch": "@@ +1,20 @@",
        "sha": "def456",
      },
    ]
    self.should_fail = False  # fail every call
    self.fail_times = 0  # or fail only the next N calls
    self.failure_rate = 0.0  # or fail this share of calls at random (fault injection)
    self.random = random.Random(7)  # fixed seed: the same "random" failures on every run
    self.status_code = 503
    self.headers: dict[str, str] = {}  # e.g. rate-limit headers on the failure response
    self.calls = []

  async def get_pull_request_files(self, repo_full_name: str, pr_number: int) -> list[dict]:
    self.calls.append((repo_full_name, pr_number))
    unlucky = self.failure_rate and self.random.random() < self.failure_rate
    if self.should_fail or self.fail_times > 0 or unlucky:
      self.fail_times = max(0, self.fail_times - 1)
      request = httpx.Request("GET", "https://api.github.com/fake")
      response = httpx.Response(self.status_code, request=request, headers=self.headers)
      raise httpx.HTTPStatusError(f"{self.status_code} error", request=request, response=response)
    return [dict(file) for file in self.files]


@pytest.fixture(scope="session")
def engine():
  """Create all tables once for the whole test run."""
  engine = create_engine(TEST_DATABASE_URL)
  Base.metadata.drop_all(engine)
  Base.metadata.create_all(engine)
  yield engine
  engine.dispose()


@pytest.fixture
def db_session(engine):
  """Empty every table before each test, then hand the test a session."""
  with engine.begin() as connection:
    connection.execute(
      text(
        "TRUNCATE job_runs, github_events, pull_request_files, pull_requests, repositories "
        "RESTART IDENTITY CASCADE"
      )
    )
  session = sessionmaker(bind=engine)()
  yield session
  session.close()


@pytest.fixture
def redis_client():
  """An empty Redis test database for each test."""
  client = Redis.from_url(TEST_REDIS_URL, decode_responses=True)
  client.flushdb()
  yield client
  client.close()


@pytest.fixture
def fake_github():
  return FakeGitHubClient()


class FakeBroker:
  """Stands in for Celery + Redis: records dispatched jobs instead of sending them."""

  def __init__(self) -> None:
    self.jobs: list[tuple[str, int]] = []  # (job_type, job_id), in dispatch order
    self.should_fail = False

  def dispatch(self, task, job_id: int) -> None:
    if self.should_fail:
      raise ConnectionError("Redis is unreachable")
    self.jobs.append((task.name.rsplit(".", 1)[-1], job_id))

  def job_ids(self, job_type: str) -> list[int]:
    return [job_id for kind, job_id in self.jobs if kind == job_type]


@pytest.fixture
def fake_broker(monkeypatch):
  import app.jobs as jobs

  broker = FakeBroker()
  monkeypatch.setattr(jobs, "dispatch", broker.dispatch)
  return broker


@pytest.fixture
def worker(monkeypatch, db_session, redis_client, fake_github, fake_broker):
  """Runs dispatched jobs in-process, against the test DB, test Redis and fake GitHub.

  Like the real worker, a failing job is recorded and does not stop the others. A job
  that asks for a retry is not run again here; test retries with task.apply() instead.
  """
  from contextlib import nullcontext

  import app.jobs as jobs

  from app.integrations.github.guard import GitHubGuard

  monkeypatch.setattr(jobs, "SessionLocal", lambda: nullcontext(db_session))
  monkeypatch.setattr(jobs, "redis_client", redis_client)
  monkeypatch.setattr(jobs, "get_github_client", lambda: fake_github)
  # Eager retries ignore countdowns, so an open circuit would loop; the breaker has its own tests.
  monkeypatch.setattr(
    jobs, "get_github_guard", lambda: GitHubGuard(redis_client, failure_threshold=10_000)
  )

  class Worker:
    def __init__(self) -> None:
      self.failures: list[Exception] = []

    def run(self) -> None:
      """Run everything dispatched so far, including the jobs those jobs dispatch."""
      while fake_broker.jobs:
        job_type, job_id = fake_broker.jobs.pop(0)
        try:
          jobs.JOB_TASKS[job_type]({"job_id": job_id})
        except Exception as error:
          db_session.rollback()
          self.failures.append(error)

  return Worker()


@pytest.fixture
def client(db_session, redis_client, fake_github, fake_broker):
  """An HTTP client for the app, wired to the test DB, test Redis, fake GitHub and fake broker."""

  def override_get_db():
    yield db_session

  app.dependency_overrides[get_db] = override_get_db
  # Ids restart at 1 in every test, so a shared cache would leak old responses.
  app.dependency_overrides[get_redis] = lambda: redis_client
  app.dependency_overrides[get_github_client] = lambda: fake_github
  yield TestClient(app)
  app.dependency_overrides.clear()
