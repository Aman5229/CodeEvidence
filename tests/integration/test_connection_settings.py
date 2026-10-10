"""The app's own connections carry the timeouts documented in doc/performance.md."""

from sqlalchemy import text

from app.db.redis import redis_client
from app.db.session import engine


def test_postgres_cancels_slow_queries_after_10_seconds():
  with engine.connect() as connection:
    assert connection.execute(text("SHOW statement_timeout")).scalar_one() == "10s"


def test_pool_checks_connections_before_use():
  assert engine.pool._pre_ping is True


def test_redis_calls_time_out():
  options = redis_client.connection_pool.connection_kwargs
  assert options["socket_timeout"] == 2
  assert options["socket_connect_timeout"] == 2
