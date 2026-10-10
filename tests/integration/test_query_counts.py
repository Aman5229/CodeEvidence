"""Query-count guards: each read endpoint runs a fixed number of SQL queries,
no matter how many rows it returns. A new N+1 (a query per row) makes these fail."""

import pytest

from app.core.config import settings
from tests.integration.test_pull_request_detail import add_files, count_queries
from tests.integration.test_pull_requests_api import add_pull_request, add_repository


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
  """Measure the database work itself, not cache hits."""
  monkeypatch.setattr(settings, "cache_enabled", False)


@pytest.fixture
def repository(db_session):
  repository = add_repository(db_session)
  for number in range(1, 31):
    pull_request = add_pull_request(db_session, repository, number, day=number)
    add_files(db_session, pull_request, 3)
  return repository


@pytest.mark.parametrize(
  ("url", "expected_queries"),
  [
    ("/repositories", 1),                                    # list
    ("/repositories/{repository_id}", 1),                    # primary-key lookup
    ("/repositories/{repository_id}/pull-requests", 2),      # repo exists + one page
    ("/repositories/{repository_id}/pull-requests?limit=30", 2),
    ("/repositories/{repository_id}/stats", 2),              # repo exists + one aggregate
  ],
)
def test_read_endpoints_run_a_fixed_number_of_queries(
  client, db_session, engine, repository, url, expected_queries
):
  path = url.format(repository_id=repository.id)
  # Like production, where each request starts with an empty session. Otherwise
  # db.get() finds the fixture's objects in memory and skips its query.
  db_session.expunge_all()

  with count_queries(engine) as statements:
    response = client.get(path)

  assert response.status_code == 200
  assert len(statements) == expected_queries, statements
