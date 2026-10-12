"""Token bucket rate limiting in Redis.

Each client has a bucket of `capacity` tokens, refilled at `per_second` tokens per second.
A request takes one token; with none left it is refused, with the time until the next token.
This allows short bursts (up to `capacity`) and a steady rate (`per_second`).

The whole check runs as one Lua script inside Redis, so it is atomic: two app processes can
never both take the last token. It uses Redis's own clock, so app servers with slightly
different clocks still share one consistent bucket.
"""

import logging

from redis import Redis

logger = logging.getLogger(__name__)

TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local per_second = tonumber(ARGV[2])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000

local bucket = redis.call('HMGET', key, 'tokens', 'updated')
local tokens = tonumber(bucket[1]) or capacity
local updated = tonumber(bucket[2]) or now
tokens = math.min(capacity, tokens + math.max(0, now - updated) * per_second)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_after = (1 - tokens) / per_second
end

redis.call('HSET', key, 'tokens', tokens, 'updated', now)
redis.call('EXPIRE', key, math.ceil(capacity / per_second) + 1)
return {allowed, tostring(retry_after)}
"""


def take_token(redis: Redis, key: str, capacity: int, per_second: float) -> tuple[bool, float]:
  """Returns (allowed, seconds until a token is available)."""
  try:
    allowed, retry_after = redis.register_script(TOKEN_BUCKET_SCRIPT)(
      keys=[key], args=[capacity, per_second]
    )
  except Exception:
    # Fail open: a Redis problem should not take the read API down with it.
    logger.warning("Rate limiter unavailable; request allowed", exc_info=True)
    return True, 0.0
  return bool(allowed), float(retry_after)
