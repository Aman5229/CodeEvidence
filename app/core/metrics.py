"""Prometheus metrics, served at GET /metrics.

- Request latency is measured in this process (a histogram, by method, route and status).
- Everything else is read at scrape time from where it lives, because the worker runs in
  other processes: jobs by status from Postgres, queue depth and cache counters from Redis,
  the circuit breaker state from Redis. Each read is independent: if one source is down,
  the others are still reported.
"""

import logging
from collections.abc import Callable, Iterator

from prometheus_client import Histogram
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.registry import Collector
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.cache import HITS_KEY, MISSES_KEY
from app.db.models import JobRun
from app.integrations.github.guard import GitHubGuard

logger = logging.getLogger(__name__)

HTTP_REQUEST_DURATION = Histogram(
  "http_request_duration_seconds",
  "Time to answer an HTTP request",
  ["method", "route", "status"],
)

CELERY_QUEUE = "celery"  # Celery's default queue: a Redis list on the broker
BREAKER_STATES = ("closed", "half_open", "open")


class StateCollector(Collector):
  def __init__(
    self,
    session_factory: Callable[[], Session],
    cache: Callable[[], Redis],
    broker: Callable[[], Redis],
  ) -> None:
    self.session_factory = session_factory
    self.cache = cache
    self.broker = broker

  def collect(self) -> Iterator[Metric]:
    for read in (self._jobs, self._queue, self._cache, self._breaker):
      try:
        yield from read()
      except Exception:
        logger.warning("Metrics source failed: %s", read.__name__, exc_info=True)

  def _jobs(self) -> Iterator[Metric]:
    jobs = GaugeMetricFamily(
      "codeevidence_jobs", "Background jobs by type and status (failed = dead letters)",
      labels=["job_type", "status"],
    )
    with self.session_factory() as db:
      rows = db.execute(
        select(JobRun.job_type, JobRun.status, func.count()).group_by(JobRun.job_type, JobRun.status)
      ).all()
    for job_type, status, count in rows:
      jobs.add_metric([job_type, status], count)
    yield jobs

  def _queue(self) -> Iterator[Metric]:
    yield GaugeMetricFamily(
      "codeevidence_queue_depth", "Jobs waiting in the queue", value=self.broker().llen(CELERY_QUEUE)
    )

  def _cache(self) -> Iterator[Metric]:
    hits, misses = self.cache().mget(HITS_KEY, MISSES_KEY)
    lookups = CounterMetricFamily("codeevidence_cache_lookups", "Cache reads", labels=["result"])
    lookups.add_metric(["hit"], int(hits or 0))
    lookups.add_metric(["miss"], int(misses or 0))
    yield lookups

  def _breaker(self) -> Iterator[Metric]:
    state = GitHubGuard(self.cache()).state()
    gauge = GaugeMetricFamily(
      "codeevidence_github_circuit_state", "1 for the circuit breaker's current state",
      labels=["state"],
    )
    for name in BREAKER_STATES:
      gauge.add_metric([name], 1 if name == state else 0)
    yield gauge
