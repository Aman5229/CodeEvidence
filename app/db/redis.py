from redis import Redis

from app.core.config import settings

# One client for the whole app. It holds a connection pool and connects on
# the first command, so the app still starts if Redis is down.
redis_client = Redis.from_url(
  settings.redis_url,
  decode_responses=True,
  socket_connect_timeout=2,  # seconds; without these a stuck Redis would hang requests forever
  socket_timeout=2,
)

def get_redis() -> Redis:
  return redis_client


# The job queue's Redis (a separate database), for readiness checks and queue-depth metrics.
broker_client = Redis.from_url(
  settings.celery_broker_url, socket_connect_timeout=2, socket_timeout=2
)


def get_broker() -> Redis:
  return broker_client

