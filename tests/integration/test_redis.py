import time

from app.db.redis import get_redis


def test_app_client_reaches_redis():
  assert get_redis().ping() is True


def test_value_round_trip_with_ttl(redis_client):
  redis_client.set("pr:1", '{"id": 1}', ex=60)

  assert redis_client.get("pr:1") == '{"id": 1}'  # str, not bytes
  assert 0 < redis_client.ttl("pr:1") <= 60


def test_value_expires_after_ttl(redis_client):
  redis_client.set("pr:1", "x", px=100)  # 100 milliseconds

  time.sleep(0.2)

  assert redis_client.get("pr:1") is None
