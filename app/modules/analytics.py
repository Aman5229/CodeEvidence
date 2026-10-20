"""Review analytics: is the reviewer useful, is it getting better, and where does it help?

Counting rules:
- Findings are counted on reviews that called the model (a cached review repeats earlier
  findings), without the findings an incremental review carried over (counted when found).
- Votes (👍 / 👎) are counted when they were given, whichever review row they were given on.
- Acceptance = useful / (useful + not useful), among the votes.
- A repeat after rejection: a finding the model raised again after someone voted 👎 on the
  same problem (same finding key) in the same repository. Learnings should make it rare.
- Risk outcomes use every scored and closed PR (no time window): does a higher risk level
  really mean fewer merges?
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import PurePosixPath

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from app.core.time_utils import utc_now
from app.db.models import ChatMessage, FindingFeedback, Learning, PullRequest, PullRequestRisk, Review, ReviewFinding

CATEGORIES = ("bug", "security", "performance", "maintainability", "tests")
RISK_LEVELS = ("low", "medium", "high")
TOP_DIRECTORIES = 8


def acceptance(useful: int, not_useful: int) -> float | None:
  return useful / (useful + not_useful) if useful + not_useful else None


@dataclass
class Votes:
  useful: int = 0
  not_useful: int = 0


@dataclass
class Analytics:
  days: int
  reviews: int = 0
  reviews_cached: int = 0
  reviews_incremental: int = 0
  cost_usd: float = 0.0
  findings_proposed: int = 0
  findings_dropped: int = 0
  findings_shown: int = 0
  votes: Votes = field(default_factory=Votes)
  repeats_after_rejection: int = 0
  learnings_total: int = 0
  learnings_enabled: int = 0
  learnings_proposed: int = 0  # from GitHub, waiting for approval
  learnings_applied: int = 0  # times learnings were part of a review
  chat_questions: int = 0
  chat_cost_usd: float = 0.0
  categories: list[dict] = field(default_factory=list)
  weeks: list[dict] = field(default_factory=list)
  models: list[dict] = field(default_factory=list)
  risk_outcomes: list[dict] = field(default_factory=list)
  directories: list[dict] = field(default_factory=list)
  drop_reasons: list[dict] = field(default_factory=list)
  tools: list[dict] = field(default_factory=list)


def directory_of(path: str) -> str:
  """The first two folders of a file's path: app/modules for app/modules/review/x.py."""
  parts = PurePosixPath(path).parts[:-1]
  return "/".join(parts[:2]) if parts else "(root)"


def week_of(day: date) -> date:
  return day - timedelta(days=day.weekday())  # its Monday


def compute_analytics(db: Session, *, days: int, repository_id: int | None) -> Analytics:
  since = utc_now() - timedelta(days=days)
  in_repository = [PullRequest.repository_id == repository_id] if repository_id is not None else []
  result = Analytics(days=days)

  # ---------- reviews ----------
  reviews = db.execute(
    select(Review.id, Review.created_at, Review.model, Review.prompt_version, Review.cached, Review.mode,
           Review.cost_usd, Review.latency_ms, Review.tools)
    .join(PullRequest, PullRequest.id == Review.pull_request_id)
    .where(Review.created_at >= since, *in_repository)
  ).all()
  result.reviews = len(reviews)
  result.reviews_cached = sum(row.cached for row in reviews)
  result.reviews_incremental = sum(row.mode == "incremental" for row in reviews)
  result.cost_usd = round(sum(row.cost_usd for row in reviews), 6)

  # ---------- findings the model raised (not cached, not carried) ----------
  findings = db.execute(
    select(ReviewFinding.review_id, ReviewFinding.path, ReviewFinding.severity, ReviewFinding.category,
           ReviewFinding.status, ReviewFinding.drop_reason, ReviewFinding.rank)
    .join(Review, Review.id == ReviewFinding.review_id)
    .join(PullRequest, PullRequest.id == Review.pull_request_id)
    .where(Review.created_at >= since, Review.cached.is_(False), ReviewFinding.carried_from_review_id.is_(None), *in_repository)
  ).all()
  shown = [row for row in findings if row.rank is not None]
  result.findings_proposed = len(findings)
  result.findings_dropped = sum(row.status == "dropped" for row in findings)
  result.findings_shown = len(shown)
  result.drop_reasons = [
    {"reason": reason, "count": count}
    for reason, count in Counter(row.drop_reason for row in findings if row.status == "dropped").most_common()
  ]

  # ---------- votes given in the window ----------
  votes = db.execute(
    select(FindingFeedback.verdict, FindingFeedback.created_at, ReviewFinding.category, Review.model, Review.prompt_version)
    .join(ReviewFinding, ReviewFinding.id == FindingFeedback.finding_id)
    .join(Review, Review.id == ReviewFinding.review_id)
    .join(PullRequest, PullRequest.id == Review.pull_request_id)
    .where(FindingFeedback.created_at >= since, FindingFeedback.verdict.is_not(None), *in_repository)
  ).all()
  result.votes = Votes(
    useful=sum(vote.verdict == "useful" for vote in votes),
    not_useful=sum(vote.verdict == "not_useful" for vote in votes),
  )

  # ---------- by category ----------
  for category in CATEGORIES:
    useful = sum(vote.verdict == "useful" and vote.category == category for vote in votes)
    not_useful = sum(vote.verdict == "not_useful" and vote.category == category for vote in votes)
    result.categories.append({
      "category": category,
      "shown": sum(row.category == category for row in shown),
      "useful": useful,
      "not_useful": not_useful,
      "acceptance": acceptance(useful, not_useful),
    })

  # ---------- by week ----------
  review_week = {row.id: week_of(row.created_at.date()) for row in reviews}
  weeks: dict[date, dict] = defaultdict(lambda: {
    "reviews": 0, "cost_usd": 0.0, "proposed": 0, "dropped": 0, "shown": 0, "useful": 0, "not_useful": 0,
  })
  for row in reviews:
    weeks[review_week[row.id]]["reviews"] += 1
    weeks[review_week[row.id]]["cost_usd"] += row.cost_usd
  for row in findings:
    week = weeks[review_week[row.review_id]]
    week["proposed"] += 1
    week["dropped"] += row.status == "dropped"
    week["shown"] += row.rank is not None
  for vote in votes:
    weeks[week_of(vote.created_at.date())][vote.verdict] += 1
  result.weeks = [
    {"week": week, **{**values, "cost_usd": round(values["cost_usd"], 6)}} for week, values in sorted(weeks.items())
  ]

  # ---------- by model and prompt ----------
  by_model: dict[tuple[str, str], dict] = defaultdict(lambda: {
    "reviews": 0, "cached": 0, "cost": 0.0, "latency": 0, "shown": 0, "dropped": 0, "useful": 0, "not_useful": 0,
  })
  review_model = {row.id: (row.model, row.prompt_version) for row in reviews}
  for row in reviews:
    stats = by_model[(row.model, row.prompt_version)]
    stats["reviews"] += 1
    stats["cached"] += row.cached
    if not row.cached:
      stats["cost"] += row.cost_usd
      stats["latency"] += row.latency_ms
  for row in findings:
    stats = by_model[review_model[row.review_id]]
    stats["shown"] += row.rank is not None
    stats["dropped"] += row.status == "dropped"
  for vote in votes:
    by_model[(vote.model, vote.prompt_version)][vote.verdict] += 1
  for (model, prompt_version), stats in sorted(by_model.items()):
    called = stats["reviews"] - stats["cached"]
    result.models.append({
      "model": model,
      "prompt_version": prompt_version,
      "reviews": stats["reviews"],
      "cached": stats["cached"],
      "avg_cost_usd": round(stats["cost"] / called, 6) if called else None,
      "avg_latency_ms": round(stats["latency"] / called) if called else None,
      "findings_shown": stats["shown"],
      "findings_dropped": stats["dropped"],
      "useful": stats["useful"],
      "not_useful": stats["not_useful"],
      "acceptance": acceptance(stats["useful"], stats["not_useful"]),
    })

  # ---------- risk level against the real outcome (all closed PRs) ----------
  outcomes = dict(
    ((level, merged), count)
    for level, merged, count in db.execute(
      select(PullRequestRisk.level, PullRequest.merged_at.is_not(None), func.count())
      .join(PullRequest, PullRequest.id == PullRequestRisk.pull_request_id)
      .where(PullRequest.status == "closed", *in_repository)
      .group_by(PullRequestRisk.level, PullRequest.merged_at.is_not(None))
    ).all()
  )
  for level in RISK_LEVELS:
    merged, unmerged = outcomes.get((level, True), 0), outcomes.get((level, False), 0)
    closed = merged + unmerged
    result.risk_outcomes.append({
      "level": level, "closed": closed, "merged": merged, "merge_rate": merged / closed if closed else None,
    })

  # ---------- where the findings are ----------
  folders: dict[str, Counter] = defaultdict(Counter)
  for row in shown:
    folders[directory_of(row.path)][row.severity] += 1
  result.directories = [
    {"directory": folder, "findings": sum(counts.values()), "high": counts["high"]}
    for folder, counts in sorted(folders.items(), key=lambda item: (-sum(item[1].values()), item[0]))[:TOP_DIRECTORIES]
  ]

  # ---------- raised again after a 👎 ----------
  earlier_finding, earlier_review, earlier_pull = aliased(ReviewFinding), aliased(Review), aliased(PullRequest)
  rejected_before = exists(
    select(FindingFeedback.id)
    .join(earlier_finding, earlier_finding.id == FindingFeedback.finding_id)
    .join(earlier_review, earlier_review.id == earlier_finding.review_id)
    .join(earlier_pull, earlier_pull.id == earlier_review.pull_request_id)
    .where(
      FindingFeedback.verdict == "not_useful",
      FindingFeedback.created_at < Review.created_at,
      earlier_finding.finding_key == ReviewFinding.finding_key,
      earlier_pull.repository_id == PullRequest.repository_id,
    )
  )
  result.repeats_after_rejection = db.scalar(
    select(func.count(ReviewFinding.id))
    .join(Review, Review.id == ReviewFinding.review_id)
    .join(PullRequest, PullRequest.id == Review.pull_request_id)
    .where(
      Review.created_at >= since, Review.cached.is_(False), ReviewFinding.carried_from_review_id.is_(None),
      ReviewFinding.rank.is_not(None), rejected_before, *in_repository,
    )
  )

  # ---------- learnings and chat ----------
  learning_filter = [Learning.repository_id == repository_id] if repository_id is not None else []
  total, enabled, proposed, applied = db.execute(
    select(
      func.count(Learning.id),
      func.count(Learning.id).filter(Learning.enabled.is_(True)),
      func.count(Learning.id).filter(Learning.enabled.is_(False), Learning.source == "github"),
      func.coalesce(func.sum(Learning.times_applied), 0),
    ).where(*learning_filter)
  ).one()
  result.learnings_total, result.learnings_enabled, result.learnings_proposed = total, enabled, proposed
  result.learnings_applied = int(applied)
  questions, chat_cost = db.execute(
    select(
      func.count(ChatMessage.id).filter(ChatMessage.role == "user"),
      func.coalesce(func.sum(ChatMessage.cost_usd), 0.0),
    )
    .join(PullRequest, PullRequest.id == ChatMessage.pull_request_id)
    .where(ChatMessage.created_at >= since, *in_repository)
  ).one()
  result.chat_questions, result.chat_cost_usd = questions, round(float(chat_cost), 6)

  # ---------- static analysis tools ----------
  tools: dict[str, dict] = defaultdict(lambda: {"runs": 0, "findings": 0, "skipped": 0})
  for row in reviews:
    if row.cached:
      continue
    for run in row.tools or []:
      stats = tools[run["name"]]
      if run.get("ran"):
        stats["runs"] += 1
        stats["findings"] += run.get("findings", 0)
      else:
        stats["skipped"] += 1
  result.tools = [{"name": name, **stats} for name, stats in sorted(tools.items())]
  return result
