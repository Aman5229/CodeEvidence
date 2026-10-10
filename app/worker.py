from celery import Celery

from app.core.config import settings

celery_app = Celery("codeevidence", broker=settings.celery_broker_url, include=["app.jobs"])

celery_app.conf.update(
  task_acks_late=True,             # acknowledge after the job finishes: at-least-once
  task_reject_on_worker_lost=True, # a killed worker process puts its job back on the queue
  worker_prefetch_multiplier=1,    # each worker process reserves one job at a time
  task_ignore_result=True,         # job status will live in Postgres, not in Redis
)
