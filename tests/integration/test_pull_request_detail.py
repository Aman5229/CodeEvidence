from contextlib import contextmanager

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import InvalidRequestError

from app.db.models import PullRequest, PullRequestFile
from tests.integration.test_pull_requests_api import (
  START,
  add_pull_request,
  add_repository,
)


def add_files(db_session, pull_request, count: int) -> None:
  for i in range(count):
    db_session.add(
      PullRequestFile(
        pull_request_id=pull_request.id,
        path=f"src/file_{i:03}.py",
        status="modified",
        additions=i + 1,
        deletions=1,
        changes=i + 2,
        patch=f"@@ -1 +1 @@ change {i}",
        patch_truncated=False,
        is_stale=False,
        created_at=START,
      )
    )
  db_session.commit()


@contextmanager
def count_queries(engine):
  """Count every SQL statement sent to the database inside the `with` block."""
  statements = []

  def record(conn, cursor, statement, parameters, context, executemany):
    statements.append(statement)

  event.listen(engine, "before_cursor_execute", record)
  try:
    yield statements
  finally:
    event.remove(engine, "before_cursor_execute", record)


@pytest.fixture
def pull_request(db_session):
  repository = add_repository(db_session)
  pull_request = add_pull_request(db_session, repository, 1, merged=True)
  add_files(db_session, pull_request, 3)
  return pull_request


def test_returns_detail_with_files_and_totals(client, pull_request):
  response = client.get(f"/pull-requests/{pull_request.id}")

  assert response.status_code == 200
  body = response.json()
  assert body["number"] == 1
  assert body["is_merged"] is True
  assert [f["path"] for f in body["files"]] == [
    "src/file_000.py",
    "src/file_001.py",
    "src/file_002.py",
  ]
  assert body["totals"] == {
    "files_changed": 3,
    "additions": 6,
    "deletions": 3,
    "lines_changed": 9,
  }


def test_patch_is_hidden_by_default(client, pull_request):
  body = client.get(f"/pull-requests/{pull_request.id}").json()

  assert "patch" not in body["files"][0]


def test_patch_is_included_when_asked(client, pull_request):
  body = client.get(f"/pull-requests/{pull_request.id}?include_patch=true").json()

  assert body["files"][0]["patch"] == "@@ -1 +1 @@ change 0"


def test_pull_request_without_files(client, db_session):
  repository = add_repository(db_session)
  pull_request = add_pull_request(db_session, repository, 1)

  body = client.get(f"/pull-requests/{pull_request.id}").json()

  assert body["files"] == []
  assert body["totals"]["files_changed"] == 0


def test_unknown_pull_request_is_404(client):
  assert client.get("/pull-requests/999").status_code == 404


@pytest.mark.parametrize("file_count", [1, 50])
def test_query_count_does_not_grow_with_files(client, db_session, engine, file_count):
  repository = add_repository(db_session)
  pull_request = add_pull_request(db_session, repository, 1)
  add_files(db_session, pull_request, file_count)
  # Read the id before counting: commit() expired the object, so touching
  # pull_request.id inside the block would itself run a SELECT.
  url = f"/pull-requests/{pull_request.id}"

  with count_queries(engine) as statements:
    response = client.get(url)

  assert response.status_code == 200
  assert len(response.json()["files"]) == file_count
  assert len(statements) == 2  # the PR, then all its files in one IN (...) query


def test_files_cannot_be_lazy_loaded(db_session, pull_request):
  """lazy='raise' guards against hidden N+1 queries (like Rails strict_loading)."""
  db_session.expire_all()
  loaded = db_session.scalars(select(PullRequest).where(PullRequest.id == pull_request.id)).one()

  with pytest.raises(InvalidRequestError):
    _ = loaded.files
