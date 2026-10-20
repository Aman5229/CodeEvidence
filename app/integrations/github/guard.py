"""Protects GitHub (and us) when it is failing or rate-limiting: shared by every worker via Redis.
The LLM provider reuses it (LLMGuard): same mechanisms, its own keys and error types.

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

class ServiceUnavailable(Exception):
  """Calls to a service are paused (rate limit or open circuit). Try again after retry_after seconds."""

  def __init__(self, service: str, reason: str, retry_after: float) -> None:
    super().__init__(f"{service} calls paused ({reason}); retry in {retry_after:.0f}s")
    self.service, self.reason, self.retry_after = service, reason, retry_after

  def __reduce__(self):
    # Celery copies exceptions between processes (pickle); rebuild from the original arguments
    return (type(self), (self.service, self.reason, self.retry_after))


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
    isinstance(error, ServiceUnavailable)
    or rate_limit_wait_seconds(error) is not None
    or is_transient(error)
  )


class GitHubGuard:
  name = "github"  # prefix of its Redis keys
  label = "GitHub"  # in error messages

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
    self.rate_limit_key = f"{self.name}:rate_limited"
    self.failures_key = f"{self.name}:breaker:failures"
    self.open_key = f"{self.name}:breaker:open"
    self.tripped_key = f"{self.name}:breaker:tripped"  # set while recovering: next result decides
    self.probe_key = f"{self.name}:breaker:probe"  # the one call allowed through while half-open

  # How errors are read. Subclasses for other services override these two.
  def rate_limit_wait(self, error: Exception) -> float | None:
    return rate_limit_wait_seconds(error)

  def is_transient(self, error: Exception) -> bool:
    return is_transient(error)

  def state(self) -> str:
    if self.redis.exists(self.open_key):
      return "open"
    if self.redis.exists(self.tripped_key):
      return "half_open"
    return "closed"

  def before_call(self) -> None:
    """Raise ServiceUnavailable if GitHub must not be called right now."""
    rate_limited_for = self.redis.ttl(self.rate_limit_key)
    if rate_limited_for > 0:
      raise ServiceUnavailable(self.label, "rate limited", rate_limited_for)

    open_for = self.redis.ttl(self.open_key)
    if open_for > 0:
      raise ServiceUnavailable(self.label, "circuit open", open_for)

    if self.redis.exists(self.tripped_key):
      # Half-open: exactly one caller gets to test GitHub; the others wait for its result.
      if not self.redis.set(self.probe_key, "1", nx=True, ex=self.open_seconds):
        raise ServiceUnavailable(self.label, "circuit half-open, testing the service", 1)

  def record_success(self) -> None:
    """GitHub answered: close the circuit and forget earlier failures."""
    self.redis.delete(self.failures_key, self.tripped_key, self.probe_key)

  def record_failure(self, error: Exception) -> None:
    wait = self.rate_limit_wait(error)
    if wait is not None:
      self.redis.set(self.rate_limit_key, "1", ex=math.ceil(wait))
      return
    if not self.is_transient(error):
      return  # a 404 or a bug says nothing about the service's health

    if self.redis.exists(self.tripped_key):
      self._open()  # the test call failed: GitHub is still down
      return
    failures = self.redis.incr(self.failures_key)
    if failures == 1:
      self.redis.expire(self.failures_key, self.failure_window_seconds)
    if failures >= self.failure_threshold:
      self._open()

  def _open(self) -> None:
    pipe = self.redis.pipeline()
    pipe.set(self.open_key, "1", ex=self.open_seconds)
    pipe.set(self.tripped_key, "1", ex=self.open_seconds * 10)
    pipe.delete(self.failures_key, self.probe_key)
    pipe.execute()
