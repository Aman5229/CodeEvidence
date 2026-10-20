"""Rate-limit pause and circuit breaker, with their state in (test) Redis."""

import time

import httpx
import pytest

from app.integrations.github.guard import GitHubGuard, ServiceUnavailable, rate_limit_wait_seconds


def github_error(status: int, headers: dict | None = None) -> httpx.HTTPStatusError:
  request = httpx.Request("GET", "https://api.github.com/x")
  response = httpx.Response(status, request=request, headers=headers or {})
  return httpx.HTTPStatusError(f"{status}", request=request, response=response)


@pytest.fixture
def guard(redis_client):
  return GitHubGuard(redis_client, failure_threshold=3, failure_window_seconds=60, open_seconds=1)


def fail(guard, times: int, status: int = 503) -> None:
  for _ in range(times):
    guard.record_failure(github_error(status))


def wait_out(seconds: float) -> None:
  time.sleep(seconds + 0.2)


# ---------- circuit breaker ----------

def test_starts_closed(guard):
  assert guard.state() == "closed"
  guard.before_call()  # does not raise


def test_opens_after_the_threshold_of_transient_failures(guard):
  fail(guard, 2)
  assert guard.state() == "closed"

  fail(guard, 1)

  assert guard.state() == "open"
  with pytest.raises(ServiceUnavailable) as raised:
    guard.before_call()
  assert 0 < raised.value.retry_after <= 1


def test_errors_that_say_nothing_about_github_health_do_not_count(guard):
  fail(guard, 10, status=404)
  guard.record_failure(KeyError("title"))

  assert guard.state() == "closed"


def test_success_resets_the_failure_count(guard):
  fail(guard, 2)
  guard.record_success()
  fail(guard, 2)

  assert guard.state() == "closed"


def test_after_the_open_period_one_caller_tests_github(guard):
  fail(guard, 3)
  wait_out(1)

  assert guard.state() == "half_open"
  guard.before_call()  # the first caller is the probe
  with pytest.raises(ServiceUnavailable):
    guard.before_call()  # everyone else waits for its result


def test_successful_probe_closes_the_circuit(guard):
  fail(guard, 3)
  wait_out(1)
  guard.before_call()

  guard.record_success()

  assert guard.state() == "closed"
  guard.before_call()
  guard.before_call()


def test_failed_probe_opens_the_circuit_again_at_once(guard):
  fail(guard, 3)
  wait_out(1)
  guard.before_call()

  fail(guard, 1)  # one failure is enough while half-open

  assert guard.state() == "open"


def test_old_failures_expire(redis_client):
  guard = GitHubGuard(redis_client, failure_threshold=3, failure_window_seconds=1)
  fail(guard, 2)
  wait_out(1)

  fail(guard, 2)

  assert guard.state() == "closed"


def test_state_is_shared_by_every_worker(redis_client, guard):
  other_worker = GitHubGuard(redis_client)
  fail(guard, 3)

  with pytest.raises(ServiceUnavailable):
    other_worker.before_call()


# ---------- rate limits ----------

def test_rate_limit_pauses_every_caller_until_the_reset_time(guard):
  reset = int(time.time()) + 30
  guard.record_failure(
    github_error(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)})
  )

  with pytest.raises(ServiceUnavailable) as raised:
    guard.before_call()
  assert "rate limited" in str(raised.value)
  assert 25 <= raised.value.retry_after <= 31
  assert guard.state() == "closed"  # a rate limit is not GitHub being broken


@pytest.mark.parametrize(
  ("status", "headers", "expected"),
  [
    (429, {"retry-after": "7"}, 7.0),
    (403, {"retry-after": "60"}, 60.0),
    (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "0"}, 1.0),  # reset passed
    (403, {}, None),  # a permission problem, not a rate limit
    (403, {"x-ratelimit-remaining": "12", "x-ratelimit-reset": "0"}, None),
    (503, {"retry-after": "5"}, None),
  ],
)
def test_rate_limit_wait_is_read_from_the_headers(status, headers, expected):
  assert rate_limit_wait_seconds(github_error(status, headers)) == expected
