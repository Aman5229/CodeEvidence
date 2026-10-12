"""Retry timing and which errors are retried."""

import httpx
import pytest

from app.jobs import RETRY_BASE_SECONDS, RETRY_MAX_SECONDS, is_retryable, retry_delay_seconds


def http_error(status: int) -> httpx.HTTPStatusError:
  request = httpx.Request("GET", "https://api.github.com/x")
  return httpx.HTTPStatusError("error", request=request, response=httpx.Response(status, request=request))


@pytest.mark.parametrize("attempt", range(8))
def test_delay_stays_between_zero_and_the_exponential_ceiling(attempt):
  ceiling = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2**attempt)

  delays = [retry_delay_seconds(attempt) for _ in range(200)]

  assert all(0 <= delay <= ceiling for delay in delays)


def test_ceiling_doubles_each_attempt_until_the_cap():
  ceilings = [max(retry_delay_seconds(a) for _ in range(500)) for a in range(4)]

  # with 500 samples the largest one is close to the ceiling: about 5, 10, 20, 40 s
  assert [round(c / RETRY_BASE_SECONDS) for c in ceilings] == [1, 2, 4, 8]


def test_delay_never_exceeds_the_cap():
  assert max(retry_delay_seconds(20) for _ in range(500)) <= RETRY_MAX_SECONDS


def test_delays_are_spread_out_not_identical():
  """Jitter: jobs that failed together must not all retry at the same moment."""
  delays = {round(retry_delay_seconds(3), 3) for _ in range(50)}

  assert len(delays) > 40


@pytest.mark.parametrize(
  ("error", "retryable"),
  [
    (httpx.ConnectTimeout("timed out"), True),
    (httpx.ReadTimeout("timed out"), True),
    (httpx.ConnectError("refused"), True),
    (http_error(429), True),
    (http_error(500), True),
    (http_error(502), True),
    (http_error(503), True),
    (http_error(504), True),
    (http_error(401), False),
    (http_error(403), False),
    (http_error(404), False),
    (http_error(422), False),
    (KeyError("title"), False),
    (ValueError("bad data"), False),
  ],
)
def test_only_transient_failures_are_retried(error, retryable):
  assert is_retryable(error) is retryable
