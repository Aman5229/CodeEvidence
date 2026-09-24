from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import PullRequest, PullRequestFile, Repository
from app.integrations.github.client import GitHubClient


async def sync_pull_request_files(
  db: Session, github: GitHubClient, repo: Repository, pr: PullRequest
) -> None:
  """Replace this PR's stored files with the current list from GitHub."""
  files = await github.get_pull_request_files(repo.full_name, pr.number)

  db.execute(delete(PullRequestFile).where(PullRequestFile.pull_request_id == pr.id))

  now = utc_now()
  for f in files:
    patch = f.get("patch")
    db.add(
      PullRequestFile(
        pull_request_id=pr.id,
        path=f["filename"],
        previous_path=f.get("previous_filename"),
        status=f["status"],
        additions=f["additions"],
        deletions=f["deletions"],
        changes=f["changes"],
        patch=patch,
        patch_size_bytes=len(patch.encode("utf-8")) if patch else None,
        patch_truncated=False,  # TODO: detect GitHub's truncated patches
        blob_sha=f.get("sha"),
        is_stale=False,  # TODO: mark files stale when head SHA moves
        created_at=now,
      )
    )
  db.flush()
