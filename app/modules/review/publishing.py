"""Post a review to GitHub, without ever posting twice.

What is posted:
- One inline comment per shown finding, with a one-click fix (a GitHub "suggestion") when the
  finding has one, and a ready-made prompt for an AI coding agent.
- A walkthrough comment in the PR's conversation: summary, review effort, risk, findings and
  a sequence diagram. Created once, then edited in place by later reviews.
- A commit status, "codeevidence/review", that fails when a shown finding is as severe as the
  repository's merge_check.block_on setting (high by default). Branch protection can require
  it to pass before merging.

Each inline comment ends with a hidden marker holding its finding key. Before posting, the PR's
existing comments are read and findings whose key is already there are skipped. So a job that
crashed after posting, a retried job, a redelivered webhook, or a new review of a new commit
that finds the same problem again never duplicates a comment. When a new commit changes the
commented lines, GitHub itself marks the old comment as outdated.

Safety: only repositories listed in PUBLISH_REPOSITORIES are ever written to.
"""

import logging
import re
from collections import Counter

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.time_utils import utc_now
from app.db.models import PullRequest, PullRequestRisk, Repository, Review, ReviewFinding
from app.integrations.github.client import GitHubClient
from app.integrations.github.guard import rate_limit_wait_seconds
from app.modules.review.fixes import agent_prompt
from app.modules.triage import Effort, pull_request_effort

logger = logging.getLogger(__name__)

MARKER = "<!-- codeevidence:{key} -->"
MARKER_PATTERN = re.compile(r"<!-- codeevidence:([0-9a-f]{32}) -->")
WALKTHROUGH_TITLE = "## CodeEvidence walkthrough"
WALKTHROUGH_MARKER = "<!-- codeevidence:walkthrough -->"
STATUS_CONTEXT = "codeevidence/review"
SEVERITIES = ("high", "medium", "low")
BLOCKING_SEVERITIES = {"high": ("high",), "medium": ("high", "medium"), "never": ()}


def publishing_allowed(repo_full_name: str) -> bool:
  allowed = {name.strip().lower() for name in settings.publish_repositories.split(",") if name.strip()}
  return repo_full_name.lower() in allowed


def dashboard_link(pull_request_id: int) -> str:
  return f"{settings.dashboard_url.rstrip('/')}/pull-requests/{pull_request_id}"


def fence(text: str, info: str = "") -> str:
  """A Markdown code block the text cannot close: the fence is longer than any run of
  backticks inside it."""
  longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
  ticks = "`" * max(3, longest + 1)
  return f"{ticks}{info}\n{text}\n{ticks}"


def comment_body(finding: ReviewFinding) -> str:
  lines = [f"**{finding.severity.capitalize()} · {finding.category}:** {finding.claim}"]
  if finding.suggestion:
    lines += ["", f"**Suggestion:** {finding.suggestion}"]
  if finding.replacement:
    lines += ["", fence(finding.replacement, "suggestion")]  # GitHub shows "Commit suggestion"
  prompt = agent_prompt(
    path=finding.path, line=finding.line, claim=finding.claim, quote=finding.quote,
    suggestion=finding.suggestion, replacement=finding.replacement,
  )
  lines += [
    "",
    "<details>",
    "<summary>🤖 Prompt for AI agents</summary>",
    "",
    fence(prompt),
    "",
    "</details>",
    "",
    f"<sub>CodeEvidence · confidence {finding.confidence:.0%} · evidence {', '.join(finding.evidence)} · "
    "react 👍 or 👎 to rate this comment, or reply to say why</sub>",
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


def severity_counts(findings: list[ReviewFinding]) -> str:
  counts = Counter(finding.severity for finding in findings)
  return ", ".join(f"{counts[severity]} {severity}" for severity in SEVERITIES if counts[severity])


def walkthrough_body(
  review: Review, shown: list[ReviewFinding], effort: Effort, risk: PullRequestRisk | None, link: str
) -> str:
  lines = [WALKTHROUGH_TITLE, "", review.summary or "_No summary for this change._", ""]
  facts = [f"**Review effort** {effort.level}/5 (about {effort.minutes} min)"]
  if risk is not None:
    facts.append(f"**Risk** {risk.level} ({risk.score}/100)")
  facts.append(f"**Findings** {len(shown)} ({severity_counts(shown)})" if shown else "**Findings** none worth a comment")
  lines.append(" · ".join(facts))
  if review.diagram:
    lines += ["", "<details>", "<summary>Sequence diagram</summary>", "", fence(review.diagram, "mermaid"), "", "</details>"]
  ran = [run for run in review.tools or [] if run.get("ran")]
  if ran:
    lines += ["", "Static analysis: " + ", ".join(f"{run['name']} ({run['findings']} on added lines)" for run in ran)]
  error = (review.config or {}).get("error")
  if error:
    lines += ["", f"⚠️ `.codeevidence.yaml`: {error}"]
  scope = "full review"
  if review.mode == "incremental" and review.compared_from_sha:
    scope = f"incremental review of the changes since {review.compared_from_sha[:7]}"
  lines += [
    "",
    f"<sub>Commit {review.head_sha[:7]} · {scope} · [open in the dashboard]({link}) · "
    "mention @codeevidence to ask a question</sub>",
    WALKTHROUGH_MARKER,
  ]
  return "\n".join(lines)


def is_walkthrough(comment: dict) -> bool:
  """Our walkthrough, not someone quoting it (a quote starts with ">")."""
  body = (comment.get("body") or "").strip()
  return body.startswith(WALKTHROUGH_TITLE) and body.endswith(WALKTHROUGH_MARKER)


async def upsert_walkthrough(github: GitHubClient, repo_full_name: str, number: int, body: str) -> None:
  """Create the walkthrough comment, or edit the one posted for an earlier review."""
  existing = next((c for c in await github.list_issue_comments(repo_full_name, number) if is_walkthrough(c)), None)
  if existing is None:
    await github.create_issue_comment(repo_full_name, number, body)
  elif existing.get("body") != body:
    await github.update_issue_comment(repo_full_name, existing["id"], body)


def merge_check(shown: list[ReviewFinding], block_on: str) -> tuple[str, str]:
  """(state, description) of the commit status for the shown findings."""
  blocking = [finding for finding in shown if finding.severity in BLOCKING_SEVERITIES.get(block_on, ("high",))]
  if blocking:
    return "failure", f"{len(blocking)} blocking finding(s): {severity_counts(blocking)}"
  if shown:
    return "success", f"No blocking findings; {len(shown)} to consider"
  return "success", "No findings"


async def post_merge_check(
  github: GitHubClient, repo_full_name: str, review: Review, shown: list[ReviewFinding], link: str
) -> str | None:
  """Post the commit status. Returns its state, or None when the token may not set statuses."""
  block_on = ((review.config or {}).get("merge_check") or {}).get("block_on", "high")
  state, description = merge_check(shown, block_on)
  try:
    await github.create_commit_status(
      repo_full_name, review.head_sha, state=state, description=description, context=STATUS_CONTEXT, target_url=link
    )
  except httpx.HTTPStatusError as error:
    # A missing permission must not lose the comments already posted; GitHub hides some
    # permission errors behind 404. Rate limits and outages still fail the job (it retries).
    if error.response.status_code in (403, 404) and rate_limit_wait_seconds(error) is None:
      logger.warning("No commit status on %s: does the token have the 'Commit statuses' permission?", repo_full_name)
      return None
    raise
  return state


async def publish_review(db: Session, github: GitHubClient, review_id: int) -> int:
  """Post the review's ranked findings, the walkthrough and the merge check. Returns how many
  inline comments were posted now."""
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
    response = await github.create_review(
      repository.full_name,
      pull_request.number,
      commit_id=review.head_sha,
      body=f"**Actionable comments posted: {len(new)}**\n\n"
      "<sub>CodeEvidence checked each finding against the diff before posting. "
      "The walkthrough is in the conversation.</sub>",
      comments=[
        {"path": f.path, "line": f.line, "side": "RIGHT", "body": comment_body(f)} for f in new
      ],
    )
    review.github_review_id = response["id"]
    # The create answer has no comment ids: read them back, matched by marker
    existing = posted_keys(await github.list_review_comments(repository.full_name, pull_request.number))

  link = dashboard_link(pull_request.id)
  effort = pull_request_effort(db, pull_request.id)
  walkthrough = walkthrough_body(review, shown, effort, db.get(PullRequestRisk, pull_request.id), link)
  await upsert_walkthrough(github, repository.full_name, pull_request.number, walkthrough)
  review.check_state = await post_merge_check(github, repository.full_name, review, shown, link)

  for finding in shown:
    finding.github_comment_id = existing.get(finding.finding_key)
  review.published_at = utc_now()
  db.commit()
  return len(new)
