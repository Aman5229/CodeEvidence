from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import parse_iso_timestamp, utc_now
from app.db.models import PullRequest, Repository


def upsert_pull_request(db: Session, repo: Repository, pr_payload: dict) -> PullRequest:
  """Create the PR if new, otherwise refresh its fields with the latest payload."""
  existing = db.execute(
    select(PullRequest).where(
      PullRequest.repository_id == repo.id,
      PullRequest.github_pr_id == pr_payload["id"],
    )
  ).scalar_one_or_none()

  if existing is not None:
    existing.title = pr_payload["title"]
    existing.body = pr_payload.get("body")
    existing.base_branch = pr_payload["base"]["ref"]
    existing.head_branch = pr_payload["head"]["ref"]
    existing.base_sha = pr_payload["base"]["sha"]
    existing.head_sha = pr_payload["head"]["sha"]
    existing.status = pr_payload["state"]
    existing.updated_at = parse_iso_timestamp(pr_payload["updated_at"])
    existing.closed_at = parse_iso_timestamp(pr_payload.get("closed_at"))
    existing.merged_at = parse_iso_timestamp(pr_payload.get("merged_at"))
    db.flush()
    return existing

  pr = PullRequest(
    repository_id=repo.id,
    github_pr_id=pr_payload["id"],
    number=pr_payload["number"],
    title=pr_payload["title"],
    body=pr_payload.get("body"),
    author_github_id=pr_payload["user"]["id"],
    author_login=pr_payload["user"]["login"],
    base_branch=pr_payload["base"]["ref"],
    head_branch=pr_payload["head"]["ref"],
    base_sha=pr_payload["base"]["sha"],
    head_sha=pr_payload["head"]["sha"],
    status=pr_payload["state"],
    created_at=parse_iso_timestamp(pr_payload["created_at"]),
    updated_at=parse_iso_timestamp(pr_payload["updated_at"]),
    closed_at=parse_iso_timestamp(pr_payload.get("closed_at")),
    merged_at=parse_iso_timestamp(pr_payload.get("merged_at")),
    ingested_at=utc_now(),
  )
  db.add(pr)
  db.flush()
  return pr
