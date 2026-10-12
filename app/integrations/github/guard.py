"""Protects GitHub (and us) when it is failing or rate-limiting: shared by every worker via Redis.

Two mechanisms:
- Rate limit pause: after a rate-limit response, no worker calls GitHub until the reset time.
- Circuit breaker: after `failure_threshold` transient failures in a row (a success resets the
  count), stop calling GitHub for a while (open), then let one call through to test it
  (half-open), and resume if it works (closed). Scattered failures are handled by retries;
  the breaker is for a sustained outage, when calling GitHub is pointless.
"""

import math
import time

import httpx
from redis import Redis

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

RATE_LIMIT_KEY = "github:rate_limited"
FAILURES_KEY = "github:breaker:failures"
OPEN_KEY = "github:breaker:open"
TRIPPED_KEY = "github:breaker:tripped"  # set while recovering: next result decides
PROBE_KEY = "github:breaker:probe"  # the one call allowed through while half-open


class GitHubUnavailable(Exception):
  """GitHub calls are paused (rate limit or open circuit). Try again after retry_after seconds."""

  def __init__(self, reason: str, retry_after: float) -> None:
    super().__init__(f"GitHub calls paused ({reason}); retry in {retry_after:.0f}s")
    self.retry_after = retry_after


def rate_limit_wait_seconds(error: Exception) -> float | None:
  """Seconds until GitHub accepts calls again, if this error is a rate-limit response."""
  if not isinstance(error, httpx.HTTPStatusError):
    return None
  if error.response.status_code not in (403, 429):
    return None
  headers = error.response.headers
  if "retry-after" in headers:  # secondary rate limits
    return float(headers["retry-after"])
  if headers.get("x-ratelimit-remaining") == "0" and "x-ratelimit-reset" in headers:
    return max(1.0, float(headers["x-ratelimit-reset"]) - time.time())  # reset is a Unix time
  return None


def is_transient(error: Exception) -> bool:
  """A failure that may succeed later: network problems and GitHub overload."""
  if isinstance(error, httpx.TransportError):  # timeouts, connection errors
    return True
  if isinstance(error, httpx.HTTPStatusError):
    return error.response.status_code in RETRYABLE_STATUS_CODES
  return False


def is_retryable(error: Exception) -> bool:
  return (
    isinstance(error, GitHubUnavailable)
    or rate_limit_wait_seconds(error) is not None
    or is_transient(error)
  )


class GitHubGuard:
  def __init__(
    self,
    redis: Redis,
    *,
    failure_threshold: int = 5,  # transient failures in a row ...
    failure_window_seconds: int = 60,  # ... within this window open the circuit
    open_seconds: int = 30,  # how long the circuit stays open
  ) -> None:
    self.redis = redis
    self.failure_threshold = failure_threshold
    self.failure_window_seconds = failure_window_seconds
    self.open_seconds = open_seconds

  def state(self) -> str:
    if self.redis.exists(OPEN_KEY):
      return "open"
    if self.redis.exists(TRIPPED_KEY):
      return "half_open"
    return "closed"

  def before_call(self) -> None:
    """Raise GitHubUnavailable if GitHub must not be called right now."""
    rate_limited_for = self.redis.ttl(RATE_LIMIT_KEY)
    if rate_limited_for > 0:
      raise GitHubUnavailable("rate limited", rate_limited_for)

    open_for = self.redis.ttl(OPEN_KEY)
    if open_for > 0:
      raise GitHubUnavailable("circuit open", open_for)

    if self.redis.exists(TRIPPED_KEY):
      # Half-open: exactly one caller gets to test GitHub; the others wait for its result.
      if not self.redis.set(PROBE_KEY, "1", nx=True, ex=self.open_seconds):
        raise GitHubUnavailable("circuit half-open, testing GitHub", 1)

  def record_success(self) -> None:
    """GitHub answered: close the circuit and forget earlier failures."""
    self.redis.delete(FAILURES_KEY, TRIPPED_KEY, PROBE_KEY)

  def record_failure(self, error: Exception) -> None:
    wait = rate_limit_wait_seconds(error)
    if wait is not None:
      self.redis.set(RATE_LIMIT_KEY, "1", ex=math.ceil(wait))
      return
    if not is_transient(error):
      return  # a 404 or a bug says nothing about GitHub's health

    if self.redis.exists(TRIPPED_KEY):
      self._open()  # the test call failed: GitHub is still down
      return
    failures = self.redis.incr(FAILURES_KEY)
    if failures == 1:
      self.redis.expire(FAILURES_KEY, self.failure_window_seconds)
    if failures >= self.failure_threshold:
      self._open()

  def _open(self) -> None:
    pipe = self.redis.pipeline()
    pipe.set(OPEN_KEY, "1", ex=self.open_seconds)
    pipe.set(TRIPPED_KEY, "1", ex=self.open_seconds * 10)
    pipe.delete(FAILURES_KEY, PROBE_KEY)
    pipe.execute()
