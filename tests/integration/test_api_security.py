"""API keys (T54) and the token-bucket rate limit (T55) on the read API."""

import hashlib
import time

import pytest
from redis import Redis
from sqlalchemy import select

from app.core.config import settings
from app.db.models import ApiKey
from app.db.redis import get_redis
from app.main import app
from app.modules.api_keys import create_api_key, revoke_api_key
from tests.integration.test_pull_request_detail import count_queries

PROTECTED = [
  "/repositories",
  "/repositories/1",
  "/repositories/1/stats",
  "/repositories/1/pull-requests",
  "/pull-requests/1",
  "/pull-requests/1/risk",
  "/pull-requests/1/review",
  "/pull-requests/1/reviews",
  "/pull-requests/insights?ids=1",
  "/overview",
  "/repositories/1/index",
  "/events/d-1",
  "/jobs",
]

# Endpoints that change something: also behind the API key
PROTECTED_WRITES = ["/pull-requests/1/review", "/repositories/1/index", "/findings/1/feedback"]


# ---------- API keys ----------

@pytest.mark.parametrize("path", PROTECTED)
def test_read_api_requires_a_key(client, path):
  response = client.get(path, headers={"X-API-Key": ""})

  assert response.status_code == 401
  assert response.json()["error"] == {
    "code": "unauthorized",
    "message": "Missing API key: send it in the X-API-Key header",
  }


@pytest.mark.parametrize("path", PROTECTED_WRITES)
def test_write_endpoints_require_a_key(client, path):
  assert client.post(path, headers={"X-API-Key": ""}, json={"verdict": "useful"}).status_code == 401


def test_unknown_key_is_rejected(client):
  response = client.get("/repositories", headers={"X-API-Key": "ce_not-a-real-key"})

  assert response.status_code == 401
  assert response.json()["error"]["message"] == "Invalid or revoked API key"


def test_revoked_key_is_rejected(client, db_session):
  api_key, key = create_api_key(db_session, "old laptop")
  assert client.get("/repositories", headers={"X-API-Key": key}).status_code == 200

  revoke_api_key(db_session, api_key)

  assert client.get("/repositories", headers={"X-API-Key": key}).status_code == 401


def test_valid_key_is_accepted(client):
  assert client.get("/repositories").status_code == 200  # the client sends its key


@pytest.mark.parametrize("path", ["/health", "/health/ready", "/metrics"])
def test_health_and_metrics_are_open(client, path):
  assert client.get(path, headers={"X-API-Key": ""}).status_code == 200


def test_only_a_hash_of_the_key_is_stored(db_session):
  api_key, key = create_api_key(db_session, "ci")

  stored = db_session.scalars(select(ApiKey).where(ApiKey.id == api_key.id)).one()
  assert stored.key_hash == hashlib.sha256(key.encode()).hexdigest()
  assert key not in (stored.key_hash, stored.key_prefix, stored.name)
  assert key.startswith("ce_") and len(key) > 40


def test_auth_costs_exactly_one_query(client, engine):
  with count_queries(engine, include_auth=True) as with_auth:
    client.get("/jobs")
  with count_queries(engine) as without_auth:
    client.get("/jobs")

  assert len(with_auth) - len(without_auth) == 1


# ---------- rate limit ----------

def test_requests_over_the_limit_get_429_with_retry_after(client, monkeypatch):
  monkeypatch.setattr(settings, "rate_limit_capacity", 3)
  monkeypatch.setattr(settings, "rate_limit_per_second", 0.01)  # about one token per 100 s

  statuses = [client.get("/repositories").status_code for _ in range(4)]

  assert statuses == [200, 200, 200, 429]
  refused = client.get("/repositories")
  assert refused.json()["error"]["code"] == "rate_limited"
  assert int(refused.headers["retry-after"]) >= 1


def test_tokens_refill_over_time(client, monkeypatch):
  monkeypatch.setattr(settings, "rate_limit_capacity", 1)
  monkeypatch.setattr(settings, "rate_limit_per_second", 20)  # a new token every 50 ms

  assert client.get("/repositories").status_code == 200
  assert client.get("/repositories").status_code == 429

  time.sleep(0.1)

  assert client.get("/repositories").status_code == 200


def test_each_key_has_its_own_bucket(client, db_session, monkeypatch):
  monkeypatch.setattr(settings, "rate_limit_capacity", 1)
  monkeypatch.setattr(settings, "rate_limit_per_second", 0.01)
  _, other_key = create_api_key(db_session, "other client")

  assert client.get("/repositories").status_code == 200
  assert client.get("/repositories").status_code == 429
  assert client.get("/repositories", headers={"X-API-Key": other_key}).status_code == 200


def test_rate_limiter_fails_open_when_redis_is_down(client, monkeypatch):
  monkeypatch.setattr(settings, "rate_limit_capacity", 1)
  broken = Redis(host="localhost", port=1, socket_connect_timeout=0.2, decode_responses=True)
  app.dependency_overrides[get_redis] = lambda: broken

  statuses = [client.get("/jobs").status_code for _ in range(3)]

  assert statuses == [200, 200, 200]  # no limit rather than no API


def test_openapi_documents_the_key_and_the_new_errors(client):
  spec = client.get("/openapi.json").json()

  assert spec["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"
  responses = spec["paths"]["/repositories"]["get"]["responses"]
  assert {"401", "429"} <= set(responses)
