"""Every error, whoever raises it, uses {"error": {"code": ..., "message": ...}}."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


def assert_error(response, status_code: int, code: str) -> dict:
  assert response.status_code == status_code
  body = response.json()
  assert set(body) == {"error"}
  assert set(body["error"]) == {"code", "message"}
  assert body["error"]["code"] == code
  assert body["error"]["message"]
  return body["error"]


# ---------- 404: raised by our routes and by the router itself ----------

def test_unknown_repository(client):
  error = assert_error(client.get("/repositories/999"), 404, "not_found")
  assert error["message"] == "Repository not found"


def test_unknown_pull_request(client):
  assert_error(client.get("/pull-requests/999"), 404, "not_found")


def test_unknown_url(client):
  assert_error(client.get("/no-such-endpoint"), 404, "not_found")


# ---------- 400 / 401 / 405 ----------

def test_bad_cursor(client):
  error = assert_error(client.get("/repositories?cursor=nonsense"), 400, "bad_request")
  assert error["message"] == "Invalid cursor"


def test_missing_webhook_header(client):
  response = client.post("/webhooks/github", content=b"{}")

  assert_error(response, 400, "bad_request")


def test_bad_webhook_signature(client):
  response = client.post(
    "/webhooks/github",
    content=b"{}",
    headers={
      "X-GitHub-Delivery": "delivery-1",
      "X-GitHub-Event": "pull_request",
      "X-Hub-Signature-256": "sha256=not-a-real-signature",
    },
  )

  assert_error(response, 401, "unauthorized")


def test_wrong_method_keeps_allow_header(client):
  response = client.delete("/repositories")

  assert_error(response, 405, "method_not_allowed")
  assert response.headers["allow"] == "GET"


# ---------- 422: FastAPI's input validation ----------

def test_limit_out_of_range(client):
  error = assert_error(client.get("/repositories?limit=0"), 422, "validation_error")
  assert error["message"].startswith("query.limit:")


def test_wrong_type_in_path(client):
  error = assert_error(client.get("/repositories/abc"), 422, "validation_error")
  assert error["message"].startswith("path.repository_id:")


def test_all_bad_fields_reported_in_one_message(client, db_session):
  from tests.integration.test_pull_requests_api import add_repository

  repository = add_repository(db_session)

  response = client.get(
    f"/repositories/{repository.id}/pull-requests", params={"limit": 0, "status": "weird"}
  )

  error = assert_error(response, 422, "validation_error")
  assert "query.limit:" in error["message"]
  assert "query.status:" in error["message"]


# ---------- 500: unexpected bugs ----------

@pytest.fixture
def broken_client():
  """A client whose database dependency crashes with a secret in the message."""

  def broken_get_db():
    raise RuntimeError("password=hunter2 leaked from the database driver")

  app.dependency_overrides[get_db] = broken_get_db
  # By default TestClient re-raises server errors in the test; we want the response.
  yield TestClient(app, raise_server_exceptions=False)
  app.dependency_overrides.clear()


def test_unexpected_error_is_500_without_internals(broken_client):
  response = broken_client.get("/repositories")

  error = assert_error(response, 500, "internal_error")
  assert error["message"] == "Internal server error"
  assert "hunter2" not in response.text


def test_unexpected_error_is_logged(broken_client, caplog):
  with caplog.at_level(logging.ERROR, logger="app.api.errors"):
    broken_client.get("/repositories")

  assert "Unhandled error on GET /repositories" in caplog.text
  assert "hunter2" in caplog.text  # the details go to the logs, not the client
