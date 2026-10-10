import hashlib
import json
import time
from collections.abc import Callable

from redis import Redis

# Webhooks will delete stale entries; the TTL is the safety net.
CACHE_TTL_SECONDS = 300

# Stampede protection: on a miss, one request builds and the others wait for it.
LOCK_TIMEOUT_SECONDS = 10  # the lock expires on its own if the builder crashes
WAIT_INTERVAL_SECONDS = 0.05
MAX_WAIT_SECONDS = 3

HITS_KEY = "cache:hits"
MISSES_KEY = "cache:misses"

def params_hash(params: dict) -> str:
  """Short, stable fingerprint of request parameters, for use in a cache key."""
  text = json.dumps(params, sort_keys=True, default=str)
  return hashlib.sha256(text.encode()).hexdigest()[:16]


def get_or_set(cache: Redis, key: str, build: Callable[[], str]) -> str:
  """Cache-aside with stampede protection: on a miss, only one caller builds."""
  cached = cache.get(key)
  if cached is not None:
    cache.incr(HITS_KEY)
    return cached
  cache.incr(MISSES_KEY)

  lock_key = f"lock:{key}"
  if cache.set(lock_key, "1", nx=True, ex=LOCK_TIMEOUT_SECONDS):
    try:
      value = build()
      cache.set(key, value, ex=CACHE_TTL_SECONDS)
      return value
    finally:
      cache.delete(lock_key)

  # Someone else is building this key: wait for their result instead of hitting the DB.
  deadline = time.monotonic() + MAX_WAIT_SECONDS
  while time.monotonic() < deadline:
    time.sleep(WAIT_INTERVAL_SECONDS)
    lock_held = cache.exists(lock_key)
    cached = cache.get(key)
    if cached is not None:
      return cached
    if not lock_held:
      break  # the builder finished without caching (e.g. a 404): build it ourselves
  return build()

def invalidate_pull_request(cache: Redis, repository_id: int, pull_request_id: int) -> None:
  """Delete every cached response that contains this pull request."""
  keys = [
    f"pull_request:{pull_request_id}:patch=0",
    f"pull_request:{pull_request_id}:patch=1",
    f"repository_stats:{repository_id}",
  ]
  keys += cache.scan_iter(match=f"pull_requests:{repository_id}:*")
  cache.delete(*keys)