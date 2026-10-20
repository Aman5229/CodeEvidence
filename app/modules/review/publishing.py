"""Post a review to GitHub as one PR review with inline comments, without ever posting twice.

Each comment ends with a hidden marker holding its finding key. Before posting, the PR's
existing comments are read and findings whose key is already there are skipped. So a job
that crashed after posting, a retried job, a redelivered webhook, or a new review of a new
commit that finds the same problem again never duplicates a comment. When a new commit
changes the commented lines, GitHub itself marks the old comment as outdated.

Safety: only repositories listed in PUBLISH_REPOSITORIES are ever written to.
"""

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.time_utils import utc_now
from app.db.models import PullRequest, Repository, Review, ReviewFinding
from app.integrations.github.client import GitHubClient

logger = logging.getLogger(__name__)

MARKER = "<!-- codeevidence:{key} -->"
MARKER_PATTERN = re.compile(r"<!-- codeevidence:([0-9a-f]{32}) -->")


def publishing_allowed(repo_full_name: str) -> bool:
  allowed = {name.strip().lower() for name in settings.publish_repositories.split(",") if name.strip()}
  return repo_full_name.lower() in allowed


def comment_body(finding: ReviewFinding) -> str:
  lines = [f"**{finding.severity.capitalize()} · {finding.category}:** {finding.claim}"]
  if finding.suggestion:
    lines += ["", f"**Suggestion:** {finding.suggestion}"]
  lines += [
    "",
    f"<sub>CodeEvidence · confidence {finding.confidence:.0%} · evidence {', '.join(finding.evidence)} · "
    "react 👍 or 👎 to rate this comment</sub>",
    MARKER.format(key=finding.finding_key),
  ]
  return "\n".join(lines)


def posted_keys(comments: list[dict]) -> dict[str, int]:
  """{finding key: comment id} of the comments we posted earlier."""
  keys = {}
  for comment in comments:
    match = MARKER_PATTERN.search(comment.get("body") or "")
    if match:
      keys.setdefault(match.group(1), comment["id"])
  return keys


async def publish_review(db: Session, github: GitHubClient, review_id: int) -> int:
  """Post the review's ranked findings. Returns how many comments were posted now."""
  review = db.scalars(
    select(Review).where(Review.id == review_id).options(selectinload(Review.findings))
  ).one_or_none()
  if review is None:
    raise ValueError(f"Review {review_id} does not exist")
  pull_request = db.get(PullRequest, review.pull_request_id)
  repository = db.get(Repository, pull_request.repository_id)
  if review.published_at is not None:
    return 0
  if not publishing_allowed(repository.full_name):
    logger.info("Not publishing to %s: not in PUBLISH_REPOSITORIES", repository.full_name)
    return 0
  if review.head_sha != pull_request.head_sha:
    logger.info("Not publishing review %s: the PR has newer commits", review.id)
    return 0

  shown = sorted((f for f in review.findings if f.rank is not None), key=lambda f: f.rank)
  existing = posted_keys(await github.list_review_comments(repository.full_name, pull_request.number))
  new = [finding for finding in shown if finding.finding_key not in existing]

  if new:
    body = review.summary or "CodeEvidence review"
    response = await github.create_review(
      repository.full_name,
      pull_request.number,
      commit_id=review.head_sha,
      body=f"{body}\n\n<sub>{len(new)} finding(s), each checked against the diff before posting.</sub>",
      comments=[
        {"path": f.path, "line": f.line, "side": "RIGHT", "body": comment_body(f)} for f in new
      ],
    )
    review.github_review_id = response["id"]
    # The create answer has no comment ids: read them back, matched by marker
    existing = posted_keys(await github.list_review_comments(repository.full_name, pull_request.number))

  for finding in shown:
    finding.github_comment_id = existing.get(finding.finding_key)
  review.published_at = utc_now()
  db.commit()
  return len(new)
