import os

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
from app.jobs import get_event_queue
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
    self.should_fail = False
    self.calls = []

  async def get_pull_request_files(self, repo_full_name: str, pr_number: int) -> list[dict]:
    self.calls.append((repo_full_name, pr_number))
    if self.should_fail:
      request = httpx.Request("GET", "https://api.github.com/fake")
      response = httpx.Response(503, request=request)
      raise httpx.HTTPStatusError("503 Service Unavailable", request=request, response=response)
    return self.files


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
        "TRUNCATE github_events, pull_request_files, pull_requests, repositories "
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


class FakeQueue:
  """Stands in for Celery in the webhook: records which events were queued."""

  def __init__(self) -> None:
    self.event_ids: list[int] = []
    self.should_fail = False

  def __call__(self, event_id: int) -> None:
    if self.should_fail:
      raise ConnectionError("Redis is unreachable")
    self.event_ids.append(event_id)


@pytest.fixture
def fake_queue():
  return FakeQueue()


@pytest.fixture
def worker(monkeypatch, db_session, redis_client, fake_github, fake_queue):
  """Runs queued jobs in-process, against the test DB, test Redis and fake GitHub.

  Like the real worker, a failing job is recorded and does not stop the others.
  """
  from contextlib import nullcontext

  import app.jobs as jobs

  pending_files: list[int] = []
  monkeypatch.setattr(jobs, "SessionLocal", lambda: nullcontext(db_session))
  monkeypatch.setattr(jobs, "redis_client", redis_client)
  monkeypatch.setattr(jobs, "get_github_client", lambda: fake_github)
  monkeypatch.setattr(jobs, "enqueue_sync_pr_files", pending_files.append)

  class Worker:
    def __init__(self) -> None:
      self.failures: list[Exception] = []

    def run(self) -> None:
      """Process everything queued so far: events first, then the file syncs they queue."""
      while fake_queue.event_ids or pending_files:
        while fake_queue.event_ids:
          self._attempt(jobs.process_event, {"event_id": fake_queue.event_ids.pop(0)})
        while pending_files:
          self._attempt(jobs.sync_pr_files, {"pull_request_id": pending_files.pop(0)})

    def _attempt(self, job, payload) -> None:
      try:
        job(payload)
      except Exception as error:
        db_session.rollback()
        self.failures.append(error)

  return Worker()


@pytest.fixture
def client(db_session, redis_client, fake_github, fake_queue):
  """An HTTP client for the app, wired to the test DB, test Redis and fake GitHub."""

  def override_get_db():
    yield db_session

  app.dependency_overrides[get_db] = override_get_db
  # Ids restart at 1 in every test, so a shared cache would leak old responses.
  app.dependency_overrides[get_redis] = lambda: redis_client
  app.dependency_overrides[get_github_client] = lambda: fake_github
  app.dependency_overrides[get_event_queue] = lambda: fake_queue
  yield TestClient(app)
  app.dependency_overrides.clear()
