import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PullRequest, Repository
from app.integrations.github.client import GitHubClient
from app.jobs import enqueue_job, sync_pr_files
from app.modules.ingestion.pull_request_sync import upsert_pull_request
from app.modules.ingestion.repository_sync import upsert_repository
from app.schemas.jobs import SyncPullRequestFilesPayload

logger = logging.getLogger(__name__)


@dataclass
class BackfillResult:
  repository: str
  queued: int = 0
  skipped: int = 0
  failed: int = 0


async def backfill_repository(
  db: Session, github: GitHubClient, repo_full_name: str, max_prs: int
) -> BackfillResult:
  """Store a repository's most recent closed PRs and queue a file sync job for each.

  The workers fetch the files in parallel. Uses the same upsert and sync code as the
  webhook, so data is stored identically. Each PR is committed on its own: one bad PR
  never loses the others. Safe to re-run: PRs already stored at the same head commit are
  skipped.
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
      db.commit()
      enqueue_job(
        db, sync_pr_files, SyncPullRequestFilesPayload(pull_request_id=pr.id), event_id=None
      )
      result.queued += 1
    except Exception:
      db.rollback()
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
