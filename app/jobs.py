from app.worker import celery_app


@celery_app.task
def ping() -> str:
  """Proves a job travels from the queue to a worker. Used to check the worker is alive."""
  return "pong"
