"""Correlation ids and JSON logs (T51), metrics (T52), liveness and readiness (T53)."""

import json
import logging

import pytest
from prometheus_client.core import Metric
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.logs import JsonFormatter, delivery_id_var, request_id_var
from app.core.metrics import StateCollector
from app.db.redis import get_redis
from app.db.session import get_db
from app.integrations.github.guard import GitHubGuard
from app.main import app
from tests.integration.test_github_webhook import pr_payload, repo_payload, send_webhook


def pr_event() -> dict:
  return {"action": "opened", "repository": repo_payload(), "pull_request": pr_payload()}


# ---------- request ids and correlation ----------

def test_every_response_carries_a_request_id(client):
  response = client.get("/health")

  assert len(response.headers["x-request-id"]) == 32


def test_a_safe_incoming_request_id_is_kept(client):
  response = client.get("/health", headers={"X-Request-ID": "trace-123"})

  assert response.headers["x-request-id"] == "trace-123"


def test_an_unsafe_incoming_request_id_is_replaced(client):
  response = client.get("/health", headers={"X-Request-ID": 'bad"\ninjected log line'})

  assert response.headers["x-request-id"] != 'bad"\ninjected log line'
  assert len(response.headers["x-request-id"]) == 32


def test_one_id_traces_a_webhook_through_the_worker(client, fake_broker, worker, caplog):
  """T51's finish line: the worker's log lines carry the webhook request's id."""
  response = send_webhook(client, "d-1", "pull_request", pr_event())
  request_id = response.headers["x-request-id"]
  caplog.clear()

  with caplog.at_level(logging.INFO, logger="app.jobs"):
    worker.run()

  job_lines = [record for record in caplog.records if record.name == "app.jobs"]
  assert {line.getMessage() for line in job_lines} >= {"Job started", "Job succeeded"}
  assert {line.request_id for line in job_lines} == {request_id}
  assert {line.delivery_id for line in job_lines} == {"d-1"}
  assert len({line.job_id for line in job_lines}) == 2  # process_event, then sync_pr_files


def test_the_follow_up_job_keeps_the_ids(client, fake_broker, worker):
  send_webhook(client, "d-1", "pull_request", pr_event())
  worker.run()

  messages = list(fake_broker.messages.values())
  assert len(messages) == 2  # sync_pr_files was queued by the worker, not by the request
  assert {(m["request_id"] is not None, m["delivery_id"]) for m in messages} == {(True, "d-1")}
  assert len({m["request_id"] for m in messages}) == 1


def test_log_lines_are_json_with_context_fields():
  request_token = request_id_var.set("req-1")
  delivery_token = delivery_id_var.set("d-9")
  try:
    record = logging.getLogger("app.test").makeRecord(
      "app.test", logging.INFO, __file__, 1, "hello %s", ("world",), None, extra={"status": 202}
    )
  finally:
    request_id_var.reset(request_token)
    delivery_id_var.reset(delivery_token)

  line = json.loads(JsonFormatter().format(record))

  assert line["msg"] == "hello world"
  assert line["level"] == "INFO"
  assert (line["request_id"], line["delivery_id"], line["status"]) == ("req-1", "d-9", 202)
  assert "job_id" not in line  # unset ids are left out


def test_each_request_writes_one_access_line(client, caplog):
  with caplog.at_level(logging.INFO, logger="app.access"):
    client.get("/repositories/123")

  lines = [record for record in caplog.records if record.name == "app.access"]
  assert len(lines) == 1
  assert (lines[0].status, lines[0].route) == (404, "/repositories/{repository_id}")
  assert lines[0].duration_ms >= 0


# ---------- metrics ----------

def samples(metrics: list[Metric], name: str) -> dict[tuple, float]:
  family = next(metric for metric in metrics if metric.name == name)
  return {tuple(sorted(s.labels.items())): s.value for s in family.samples}


@pytest.fixture
def collector(engine, redis_client):
  # The test database and test Redis; the queue is read from a list in the same test Redis.
  return StateCollector(sessionmaker(bind=engine), lambda: redis_client, lambda: redis_client)


def test_metrics_endpoint_has_request_latency_by_route_template(client):
  client.get("/repositories/123")
  client.get("/no-such-page")

  body = client.get("/metrics").text

  assert 'http_request_duration_seconds_count{method="GET",route="/repositories/{repository_id}",status="404"}' in body
  assert 'route="unmatched"' in body  # unknown paths share one label value
  assert "codeevidence_jobs" in body and "codeevidence_queue_depth" in body


def test_jobs_by_status_including_dead_letters(client, worker, fake_github, collector):
  send_webhook(client, "d-1", "pull_request", pr_event())
  fake_github.should_fail = True
  fake_github.status_code = 404  # the file sync becomes a dead letter
  worker.run()

  jobs = samples(list(collector.collect()), "codeevidence_jobs")

  assert jobs[(("job_type", "process_event"), ("status", "succeeded"))] == 1
  assert jobs[(("job_type", "sync_pr_files"), ("status", "failed"))] == 1


def test_queue_depth_cache_lookups_and_breaker_state(redis_client, collector):
  redis_client.rpush("celery", "job-1", "job-2", "job-3")
  redis_client.set("cache:hits", 5)  # what get_or_set counts on every cached read
  redis_client.set("cache:misses", 2)
  guard = GitHubGuard(redis_client, failure_threshold=1)
  guard.before_call()
  guard.record_failure(_transient_error())

  metrics = list(collector.collect())

  assert samples(metrics, "codeevidence_queue_depth") == {(): 3}
  lookups = samples(metrics, "codeevidence_cache_lookups")
  assert lookups[(("result", "hit"),)] == 5 and lookups[(("result", "miss"),)] == 2
  breaker = samples(metrics, "codeevidence_github_circuit_state")
  assert breaker[(("state", "open"),)] == 1 and breaker[(("state", "closed"),)] == 0


def test_one_broken_source_does_not_hide_the_others(redis_client):
  def broken_database():
    raise RuntimeError("database is down")

  collector = StateCollector(broken_database, lambda: redis_client, lambda: redis_client)

  names = {metric.name for metric in collector.collect()}

  assert "codeevidence_jobs" not in names
  assert {"codeevidence_queue_depth", "codeevidence_github_circuit_state"} <= names


def _transient_error():
  import httpx

  request = httpx.Request("GET", "https://api.github.com/x")
  return httpx.HTTPStatusError("503", request=request, response=httpx.Response(503, request=request))


# ---------- liveness and readiness ----------

def test_ready_when_database_cache_and_queue_answer(client):
  response = client.get("/health/ready")

  assert response.status_code == 200
  assert response.json() == {
    "status": "ready",
    "checks": {"database": "ok", "cache": "ok", "queue": "ok"},
  }


def test_not_ready_when_the_database_is_down(client):
  """T53's finish line: readiness fails if the database is down."""
  dead_engine = create_engine(
    "postgresql+psycopg://x:y@localhost:1/none", connect_args={"connect_timeout": 1}
  )

  def dead_database():
    with sessionmaker(bind=dead_engine)() as session:
      yield session

  app.dependency_overrides[get_db] = dead_database

  response = client.get("/health/ready")

  assert response.status_code == 503
  assert response.json()["status"] == "not_ready"
  assert response.json()["checks"]["database"] == "unavailable"
  assert client.get("/health").status_code == 200  # liveness is unaffected


def test_not_ready_when_the_cache_is_down(client):
  app.dependency_overrides[get_redis] = lambda: Redis(
    host="localhost", port=1, socket_connect_timeout=0.2
  )

  response = client.get("/health/ready")

  assert response.status_code == 503
  assert response.json()["checks"] == {"database": "ok", "cache": "unavailable", "queue": "ok"}
