"""On a miss, only one caller builds the value; the others wait for it."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException

from app.core.cache import HITS_KEY, MISSES_KEY, get_or_set

CALLERS = 20


def run_at_once(func):
  """Call func from CALLERS threads that all start at the same moment."""
  start_together = threading.Barrier(CALLERS)

  def caller():
    start_together.wait()
    return func()

  with ThreadPoolExecutor(max_workers=CALLERS) as pool:
    return [pool.submit(caller) for _ in range(CALLERS)]


def test_concurrent_misses_build_only_once(redis_client):
  calls = []

  def slow_build():
    calls.append(1)
    time.sleep(0.2)  # long enough for every other caller to miss and wait
    return '{"value": 1}'

  futures = run_at_once(lambda: get_or_set(redis_client, "stats:1", slow_build))

  assert [future.result() for future in futures] == ['{"value": 1}'] * CALLERS
  assert len(calls) == 1


def test_lock_is_released_after_a_build(redis_client):
  get_or_set(redis_client, "stats:1", lambda: "x")

  assert redis_client.exists("lock:stats:1") == 0


def test_failed_build_releases_lock_and_waiters_do_not_hang(redis_client):
  def failing_build():
    time.sleep(0.2)
    raise HTTPException(status_code=404, detail="Repository not found")

  started = time.monotonic()
  futures = run_at_once(lambda: get_or_set(redis_client, "stats:1", failing_build))

  for future in futures:
    with pytest.raises(HTTPException):
      future.result()
  assert time.monotonic() - started < 2  # waiters stop as soon as the lock is gone
  assert redis_client.exists("lock:stats:1") == 0
  assert redis_client.exists("stats:1") == 0


def test_hits_and_misses_are_counted(redis_client):
  get_or_set(redis_client, "stats:1", lambda: "x")  # miss
  get_or_set(redis_client, "stats:1", lambda: "x")  # hit
  get_or_set(redis_client, "stats:1", lambda: "x")  # hit

  assert redis_client.get(MISSES_KEY) == "1"
  assert redis_client.get(HITS_KEY) == "2"
