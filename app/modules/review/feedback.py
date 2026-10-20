"""Feedback on findings: from GitHub (reactions, replies, resolved threads) and the dashboard.

Each piece of GitHub feedback stores the id of the GitHub object it came from, so reading
the same reaction or webhook twice records it once.

What each signal means:
- 👍 ❤️ 🎉 = useful; 👎 😕 = not useful. The clearest signal.
- A reply: stored with its text and no verdict; a person reads it.
- A resolved thread: no verdict either. It can mean "fixed it" or "dismissed it".
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import FindingFeedback, PullRequest, Repository, Review, ReviewFinding
from app.integrations.github.client import GitHubClient

VERDICT_BY_REACTION = {"+1": "useful", "heart": "useful", "hooray": "useful", "-1": "not_useful", "confused": "not_useful"}
FEEDBACK_EVENTS = {"pull_request_review_comment", "pull_request_review_thread"}


def record_feedback(
  db: Session,
  finding: ReviewFinding,
  *,
  source: str,
  verdict: str | None,
  body: str | None = None,
  github_user: str | None = None,
  external_id: str | None = None,
) -> FindingFeedback | None:
  """Store one piece of feedback. Returns None if this GitHub object was recorded before."""
  if external_id and db.scalar(select(FindingFeedback.id).where(FindingFeedback.external_id == external_id)):
    return None
  feedback = FindingFeedback(
    finding_id=finding.id,
    source=source,
    verdict=verdict,
    body=body,
    github_user=github_user,
    external_id=external_id,
    created_at=utc_now(),
  )
  db.add(feedback)
  db.flush()
  return feedback


def finding_for_comment(db: Session, comment_id: int | None) -> ReviewFinding | None:
  if comment_id is None:
    return None
  # Later reviews that find the same problem point at the same comment: take the newest finding
  return db.scalars(
    select(ReviewFinding).where(ReviewFinding.github_comment_id == comment_id).order_by(ReviewFinding.id.desc())
  ).first()


def feedback_from_webhook(db: Session, event_type: str, payload: dict) -> int:
  """Record replies to our comments and resolved threads. Returns how many were recorded."""
  if event_type == "pull_request_review_comment" and payload.get("action") == "created":
    comment = payload["comment"]
    finding = finding_for_comment(db, comment.get("in_reply_to_id"))
    if finding is not None and record_feedback(
      db, finding, source="github_reply", verdict=None, body=comment.get("body"),
      github_user=(comment.get("user") or {}).get("login"), external_id=f"comment:{comment['id']}",
    ):
      return 1
  if event_type == "pull_request_review_thread" and payload.get("action") == "resolved":
    comments = payload.get("thread", {}).get("comments") or [{}]
    finding = finding_for_comment(db, comments[0].get("id"))
    if finding is not None and record_feedback(
      db, finding, source="github_resolved", verdict=None,
      github_user=(payload.get("sender") or {}).get("login"),
      external_id=f"resolved:{comments[0]['id']}:{payload.get('thread', {}).get('node_id', '')}",
    ):
      return 1
  return 0


async def collect_reactions(db: Session, github: GitHubClient, review: Review) -> int:
  """Read reactions on a published review's comments (GitHub sends no webhook for them)."""
  pull_request = db.get(PullRequest, review.pull_request_id)
  repository = db.get(Repository, pull_request.repository_id)
  findings = db.scalars(
    select(ReviewFinding).where(ReviewFinding.review_id == review.id, ReviewFinding.github_comment_id.is_not(None))
  ).all()
  recorded = 0
  for finding in findings:
    for reaction in await github.list_comment_reactions(repository.full_name, finding.github_comment_id):
      verdict = VERDICT_BY_REACTION.get(reaction.get("content"))
      if verdict and record_feedback(
        db, finding, source="github_reaction", verdict=verdict,
        github_user=(reaction.get("user") or {}).get("login"), external_id=f"reaction:{reaction['id']}",
      ):
        recorded += 1
  db.commit()
  return recorded
