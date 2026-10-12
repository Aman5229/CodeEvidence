import logging

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.redis import get_broker, get_redis
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness():
  """Liveness: the process is running. Checks nothing else, so a database outage does not
  make the orchestrator restart healthy app processes (a restart would not fix it)."""
  return {"status": "ok"}


@router.get("/health/ready")
def readiness(
  response: Response,
  db: Session = Depends(get_db),
  cache: Redis = Depends(get_redis),
  broker: Redis = Depends(get_broker),
):
  """Readiness: can this process serve requests now? 503 if a dependency is down, so a load
  balancer stops sending traffic here until it recovers."""
  checks = {
    "database": _check(lambda: db.execute(text("SELECT 1"))),
    "cache": _check(cache.ping),
    "queue": _check(broker.ping),
  }
  ready = all(result == "ok" for result in checks.values())
  if not ready:
    response.status_code = 503
  return {"status": "ready" if ready else "not_ready", "checks": checks}


def _check(probe) -> str:
  try:
    probe()
    return "ok"
  except Exception:
    logger.warning("Readiness check failed", exc_info=True)
    return "unavailable"  # details go to the logs, not to whoever asks


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
  """Prometheus text format, for a Prometheus server to scrape."""
  return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
