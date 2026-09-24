import os

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import models  # noqa: F401  (registers all tables on Base.metadata)
from app.db.base import Base
from app.db.session import get_db
from app.integrations.github.client import get_github_client
from app.main import app

# A SEPARATE database, so tests never touch your real data.
TEST_DATABASE_URL = os.getenv(
  "TEST_DATABASE_URL",
  "postgresql+psycopg://codeevidence:codeevidence@localhost:5433/codeevidence_test",
)


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
def fake_github():
  return FakeGitHubClient()


@pytest.fixture
def client(db_session, fake_github):
  """An HTTP client for the app, wired to the test DB and the fake GitHub."""

  def override_get_db():
    yield db_session

  app.dependency_overrides[get_db] = override_get_db
  app.dependency_overrides[get_github_client] = lambda: fake_github
  yield TestClient(app)
  app.dependency_overrides.clear()
