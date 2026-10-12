import asyncio

import httpx
import pytest
from sqlalchemy import func, select

from app.db.models import JobRun, PullRequest, PullRequestFile, Repository
from app.modules.ingestion.backfill import backfill_repository


def make_pr(number: int) -> dict:
  return {
    "id": 5000 + number,
    "number": number,
    "title": f"PR {number}",
    "body": None,
    "state": "closed",
    "user": {"id": 1, "login": "dev"},
    "base": {"ref": "main", "sha": "a" * 40},
    "head": {"ref": f"feature-{number}", "sha": f"{number:040d}"},
    "created_at": "2024-06-01T09:00:00Z",
    "updated_at": "2024-06-02T09:00:00Z",
    "closed_at": "2024-06-02T09:00:00Z",
    "merged_at": "2024-06-02T09:00:00Z" if number % 2 == 0 else None,
  }


class FakeBackfillGitHub:
  def __init__(self, pr_count: int = 3) -> None:
    self.pulls = [make_pr(n) for n in range(1, pr_count + 1)]
    self.failing_pr_numbers: set[int] = set()
    self.rate_limited = False
    self.file_calls = 0

  async def get_repository(self, repo_full_name: str) -> dict:
    return {
      "id": 42,
      "full_name": repo_full_name,
      "owner": {"login": repo_full_name.split("/")[0]},
      "default_branch": "main",
      "html_url": f"https://github.com/{repo_full_name}",
      "private": False,
      "created_at": "2020-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z",
    }

  async def list_closed_pull_requests(self, repo_full_name: str, limit: int) -> list[dict]:
    return self.pulls[:limit]

  async def get_pull_request_files(self, repo_full_name: str, pr_number: int) -> list[dict]:
    self.file_calls += 1
    if self.rate_limited or pr_number in self.failing_pr_numbers:
      status = 403 if self.rate_limited else 500
      request = httpx.Request("GET", "https://api.github.com/fake")
      raise httpx.HTTPStatusError("error", request=request, response=httpx.Response(status, request=request))
    return [
      {"filename": f"src/file_{pr_number}.py", "status": "modified",
       "additions": 3, "deletions": 1, "changes": 4, "patch": "@@", "sha": "s"},
    ]


def count(db_session, model) -> int:
  return db_session.execute(select(func.count()).select_from(model)).scalar_one()


def run(db_session, github, max_prs: int = 10):
  return asyncio.run(backfill_repository(db_session, github, "octo/demo", max_prs))


@pytest.fixture
def backfill_worker(monkeypatch, worker):
  """The in-process worker, fetching files from the backfill's fake GitHub."""
  import app.jobs as jobs

  def use(github):
    monkeypatch.setattr(jobs, "get_github_client", lambda: github)
    return worker

  return use


def test_backfill_stores_prs_and_queues_one_file_sync_each(db_session, fake_broker):
  github = FakeBackfillGitHub(pr_count=3)

  result = run(db_session, github)

  assert (result.queued, result.skipped, result.failed) == (3, 0, 0)
  assert count(db_session, Repository) == 1
  assert count(db_session, PullRequest) == 3
  assert github.file_calls == 0  # no file fetching in the backfill itself
  assert len(fake_broker.job_ids("sync_pr_files")) == 3
  assert all(job.event_id is None for job in db_session.scalars(select(JobRun)))


def test_workers_fetch_the_files(db_session, fake_broker, backfill_worker):
  github = FakeBackfillGitHub(pr_count=3)
  run(db_session, github)

  backfill_worker(github).run()

  assert count(db_session, PullRequestFile) == 3
  assert github.file_calls == 3


def test_rerun_skips_prs_already_stored(db_session, fake_broker):
  github = FakeBackfillGitHub(pr_count=3)
  run(db_session, github)

  result = run(db_session, github)

  assert (result.queued, result.skipped) == (0, 3)
  assert len(fake_broker.job_ids("sync_pr_files")) == 3  # nothing queued again


def test_one_pr_whose_files_fail_does_not_stop_the_others(db_session, fake_broker,
                                                          backfill_worker):
  github = FakeBackfillGitHub(pr_count=3)
  github.failing_pr_numbers = {2}  # GitHub returns 500 for PR 2
  run(db_session, github)

  worker = backfill_worker(github)
  worker.run()

  assert count(db_session, PullRequest) == 3
  assert count(db_session, PullRequestFile) == 2
  assert len(worker.failures) == 1
  statuses = sorted(db_session.scalars(select(JobRun.status)).all())
  assert statuses == ["retrying", "succeeded", "succeeded"]  # a 500 is retried by Celery


def test_queueing_failure_is_counted_and_does_not_stop_the_others(db_session, fake_broker):
  github = FakeBackfillGitHub(pr_count=3)
  fake_broker.should_fail = True

  result = run(db_session, github)

  assert (result.queued, result.failed) == (0, 3)
