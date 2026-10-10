"""The Celery settings promised in doc/decisions.md (at-least-once delivery)."""

from app.jobs import ping
from app.worker import celery_app


def test_jobs_are_acknowledged_after_they_finish():
  assert celery_app.conf.task_acks_late is True
  assert celery_app.conf.task_reject_on_worker_lost is True


def test_each_worker_process_reserves_one_job_at_a_time():
  assert celery_app.conf.worker_prefetch_multiplier == 1


def test_results_are_not_stored_in_redis():
  assert celery_app.conf.task_ignore_result is True


def test_ping_job_is_registered_and_runs():
  assert "app.jobs.ping" in celery_app.tasks
  assert ping() == "pong"  # called directly, like perform_now
