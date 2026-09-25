import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PullRequest, Repository
from app.integrations.github.client import GitHubClient
from app.modules.ingestion.file_sync import sync_pull_request_files
from app.modules.ingestion.pull_request_sync import upsert_pull_request
from app.modules.ingestion.repository_sync import upsert_repository

logger = logging.getLogger(__name__)

RATE_LIMIT_STATUS_CODES = (403, 429)


@dataclass
class BackfillResult:
  repository: str
  stored: int = 0
  skipped: int = 0
  failed: int = 0


async def backfill_repository(
  db: Session, github: GitHubClient, repo_full_name: str, max_prs: int
) -> BackfillResult:
  """Load a repository's most recent closed PRs (and their files) into the database.

  Reuses the same upsert/sync functions as the webhook, so data is stored identically.
  Each PR is committed on its own: one bad PR never loses the others.
  Safe to re-run: PRs already stored at the same head commit are skipped.
  """
  result = BackfillResult(repository=repo_full_name)

  repo = upsert_repository(db, await github.get_repository(repo_full_name))
  db.commit()

  pr_payloads = await github.list_closed_pull_requests(repo_full_name, limit=max_prs)

  for pr_payload in pr_payloads:
    if _already_stored(db, repo, pr_payload):
      result.skipped += 1
      continue

    try:
      pr = upsert_pull_request(db, repo, pr_payload)
      await sync_pull_request_files(db, github, repo, pr)
      db.commit()
      result.stored += 1
    except Exception as error:
      db.rollback()
      if _is_rate_limited(error):
        raise  # stop everything: every further request would fail too
      logger.exception("Failed to backfill %s#%s", repo_full_name, pr_payload.get("number"))
      result.failed += 1

  return result


def _already_stored(db: Session, repo: Repository, pr_payload: dict) -> bool:
  existing_head_sha = db.execute(
    select(PullRequest.head_sha).where(
      PullRequest.repository_id == repo.id,
      PullRequest.github_pr_id == pr_payload["id"],
    )
  ).scalar_one_or_none()
  return existing_head_sha == pr_payload["head"]["sha"]


def _is_rate_limited(error: Exception) -> bool:
  return (
    isinstance(error, httpx.HTTPStatusError)
    and error.response.status_code in RATE_LIMIT_STATUS_CODES
  )
