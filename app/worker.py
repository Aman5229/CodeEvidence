from celery import Celery
from celery.signals import setup_logging

from app.core.config import settings
from app.core.logs import configure_logging

celery_app = Celery("codeevidence", broker=settings.celery_broker_url, include=["app.jobs"])

celery_app.conf.update(
  task_acks_late=True,             # acknowledge after the job finishes: at-least-once
  task_reject_on_worker_lost=True, # a killed worker process puts its job back on the queue
  worker_prefetch_multiplier=1,    # each worker process reserves one job at a time
  task_ignore_result=True,         # job status will live in Postgres, not in Redis
)


@setup_logging.connect
def use_json_logs(**kwargs) -> None:
  """Replace Celery's own log setup with the app's JSON logs (same format as the API)."""
  configure_logging(settings.log_level)

