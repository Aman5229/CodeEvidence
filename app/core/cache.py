import hashlib
import json
from collections.abc import Callable

from redis import Redis

# Webhooks will delete stale entries; the TTL is the safety net.
CACHE_TTL_SECONDS = 300

def params_hash(params: dict) -> str:
  """Short, stable fingerprint of request parameters, for use in a cache key."""
  text = json.dumps(params, sort_keys=True, default=str)
  return hashlib.sha256(text.encode()).hexdigest()[:16]


def get_or_set(cache: Redis, key: str, build: Callable[[], str]) -> str:
  """Cache-aside: return the cached value, or build it, store it and return it."""
  cached = cache.get(key)
  if cached is not None:
    return cached
  value = build()
  cache.set(key, value, ex=CACHE_TTL_SECONDS)
  return value