"""Review a PR: settings, evidence, a cached result or the pipeline, then store it all.

1. The repository's settings (.codeevidence.yaml) and guideline files, from its default branch.
2. Full or incremental. After new commits on top of the last review, only the files changed
   since then are reviewed, and that review's findings on the other files are carried over:
   their code did not change, so they still hold. A rebase or force-push, a new prompt or
   model, or mode="full" means a full review.
3. The learnings and path instructions that apply to the files under review.
4. Evidence (with static analysis tools), then a cached result or the model.
"""

import hashlib
from dataclasses import asdict, dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.time_utils import utc_now
from app.db.models import PullRequest, PullRequestRisk, Repository, Review, ReviewFinding
from app.integrations.github.client import GitHubClient, is_not_found
from app.modules.code.embeddings import Embedder
from app.modules.code.evidence import (
  EvidenceBundle,
  EvidenceItem,
  EvidenceOptions,
  collect_evidence,
  reviewable_files,
)
from app.modules.code.signals import FileDiff
from app.modules.review.diagram import DIAGRAM_PROMPT
from app.modules.review.findings import Finding
from app.modules.review.learnings import mark_applied, relevant_learnings
from app.modules.review.llm import CostMeter, LLMProvider
from app.modules.review.pipeline import run_pipeline
from app.modules.review.prompts import REVIEW_PROMPT, SUMMARY_PROMPT, review_messages, summary_messages
from app.modules.review.ranking import finding_key
from app.modules.review.repo_config import instructions_for, load_repo_config

STATUS_COMPLETED = "completed"
COMPARE_MAX_FILES = 300  # GitHub lists at most this many files in a comparison
LEARNING_QUERY_CHARS = 2000


def review_cache_key(bundle: EvidenceBundle, model: str, *context: str) -> str:
  """A hash of everything that decides the result: the exact model input (prompt version,
  evidence, model) plus `context` (profile, risk level, the whole PR for the summary, the
  carried findings...). Same key, same result: the stored answer is reused. A new prompt
  version or a changed diff gives a new key."""
  system, user = review_messages(bundle)
  text = "\0".join([REVIEW_PROMPT, SUMMARY_PROMPT, model, system, user, *context])
  return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Plan:
  mode: str  # full, incremental
  base: Review | None = None  # incremental: the review it builds on
  changed: frozenset[str] | None = None  # incremental: files changed since the base's commit


async def plan_review(
  db: Session, github: GitHubClient, repository: Repository, pull_request: PullRequest, mode: str, model: str
) -> Plan:
  """Full or incremental (see the module docstring)."""
  if mode == "full":
    return Plan("full")
  latest = db.scalars(
    select(Review)
    .where(Review.pull_request_id == pull_request.id, Review.status == STATUS_COMPLETED)
    .order_by(Review.created_at.desc(), Review.id.desc())
    .limit(1)
  ).first()
  base = latest
  if latest is not None and latest.head_sha == pull_request.head_sha:
    # No new commit since the last review: do what it did, so an unchanged PR is a cache hit
    base = db.get(Review, latest.base_review_id) if latest.mode == "incremental" and latest.base_review_id else None
  if (
    base is None
    or base.head_sha == pull_request.head_sha
    or base.prompt_version != REVIEW_PROMPT
    or base.model != model
  ):
    return Plan("full")
  try:
    comparison = await github.compare_commits(repository.full_name, base.head_sha, pull_request.head_sha)
  except httpx.HTTPStatusError as error:
    if is_not_found(error):  # the earlier commit is gone (force-push): start again
      return Plan("full")
    raise
  files = comparison.get("files") or []
  if comparison.get("status") != "ahead" or len(files) >= COMPARE_MAX_FILES:
    return Plan("full")  # rebased or force-pushed, or more files than the comparison lists
  changed = {file["filename"] for file in files} | {file["previous_filename"] for file in files if file.get("previous_filename")}
  return Plan("incremental", base, frozenset(changed))


def carry_over(db: Session, base: Review, paths: set[str]) -> tuple[list[ReviewFinding], list[Finding], list[EvidenceItem]]:
  """The base review's shown findings on `paths` (files that did not change since), as stored
  rows, as findings to rank, and the evidence they cite, renumbered C1, C2..."""
  rows = db.scalars(
    select(ReviewFinding)
    .where(ReviewFinding.review_id == base.id, ReviewFinding.rank.is_not(None), ReviewFinding.path.in_(paths))
    .order_by(ReviewFinding.rank)
  ).all() if paths else []
  stored = {item["id"]: item for item in base.evidence}
  renamed: dict[str, str] = {}
  items: list[EvidenceItem] = []
  for row in rows:
    for item_id in row.evidence:
      if item_id in stored and item_id not in renamed:
        renamed[item_id] = f"C{len(renamed) + 1}"
        item = stored[item_id]
        items.append(EvidenceItem(**{**item, "id": renamed[item_id], "new_lines": tuple(item.get("new_lines", ()))}))
  findings = [
    Finding.model_construct(  # verified when first found: not validated again
      path=row.path, line=row.line, severity=row.severity, category=row.category, claim=row.claim,
      quote=row.quote, evidence=[renamed[i] for i in row.evidence if i in renamed], suggestion=row.suggestion,
      replacement=row.replacement, confidence=row.confidence,
    )
    for row in rows
  ]
  return list(rows), findings, items


def learning_query(pull_request: PullRequest, files: list[FileDiff]) -> str:
  """What the learnings are matched against: the PR's title, files and added code."""
  added = "\n".join(line.text for file in files for hunk in file.hunks for line in hunk.added)
  text = "\n".join([pull_request.title, *(file.path for file in files), added])
  return text[:LEARNING_QUERY_CHARS]


async def review_pull_request(
  db: Session,
  github: GitHubClient,
  embedder: Embedder,
  llm: LLMProvider,
  pull_request_id: int,
  *,
  budget_usd: float,
  mode: str = "auto",
) -> Review:
  """mode: "auto" (incremental when possible) or "full"."""
  pull_request = db.get(PullRequest, pull_request_id)
  if pull_request is None:
    raise ValueError(f"Pull request {pull_request_id} does not exist")
  repository = db.get(Repository, pull_request.repository_id)
  loaded = await load_repo_config(github, repository)
  config = loaded.config
  plan = await plan_review(db, github, repository, pull_request, mode, llm.model)

  files, _ = reviewable_files(db, pull_request, config.exclude)
  under_review = [file for file in files if plan.changed is None or file.path in plan.changed]
  paths = [file.path for file in under_review]
  learnings = relevant_learnings(db, embedder, repository.id, paths, learning_query(pull_request, under_review))
  options = EvidenceOptions(
    budget=settings.review_token_budget,
    only_paths=set(plan.changed) if plan.changed is not None else None,
    exclude=config.exclude,
    learnings=[(learning.id, learning.text, learning.path_glob) for learning in learnings],
    instructions=instructions_for(paths, config),
    guidelines=loaded.guidelines,
    tools=config.tools.model_dump() if settings.tools_enabled else None,
  )
  collected = await collect_evidence(db, github, embedder, pull_request, options)
  bundle = collected.bundle

  carried_rows: list[ReviewFinding] = []
  carried: list[Finding] = []
  carried_items: list[EvidenceItem] = []
  if plan.base is not None:
    unchanged = {file.path for file in files} - plan.changed
    carried_rows, carried, carried_items = carry_over(db, plan.base, unchanged)
  risk = db.get(PullRequestRisk, pull_request.id)
  risk_level = risk.level if risk else None
  nothing_new = plan.base is not None and not any(item.kind == "hunk" for item in bundle.items)

  context = [f"profile={config.profile}", f"risk={risk_level}", f"diagram={DIAGRAM_PROMPT}"]
  if plan.base is not None:
    context += [
      f"base={plan.base.id}",
      "carried=" + ",".join(str(row.id) for row in carried_rows),
      summary_messages(collected.summary_bundle)[1],
    ]
  key = review_cache_key(bundle, llm.model, *context)
  review = Review(
    pull_request_id=pull_request.id,
    head_sha=pull_request.head_sha,
    prompt_version=REVIEW_PROMPT,
    model=llm.model,
    cache_key=key,
    evidence=[*bundle.to_json(), *(asdict(item) for item in carried_items)],
    created_at=utc_now(),
    mode=plan.mode,
    base_review_id=plan.base.id if plan.base else None,
    compared_from_sha=plan.base.head_sha if plan.base else None,
    config=loaded.summary(),
    tools=[asdict(run) for run in collected.tool_runs] if options.tools is not None else None,
  )

  cached = db.scalars(
    select(Review)  # an answer that could not be read is asked for again, not reused
    .where(Review.cache_key == key, Review.status == STATUS_COMPLETED, Review.error.is_(None))
    .order_by(Review.id.desc())
    .options(selectinload(Review.findings))
    .limit(1)
  ).first()
  if cached is not None:
    _copy_result(review, cached)
  else:
    meter = CostMeter(llm, budget_usd)
    result = run_pipeline(
      meter, bundle, risk_level,
      with_summary=not nothing_new, summary_bundle=collected.summary_bundle, profile=config.profile,
      with_diagram=not nothing_new, carried=carried, carried_evidence=carried_items,
    )
    if nothing_new:  # only files that are not reviewed changed: the earlier review still holds
      result.summary, result.diagram = plan.base.summary, plan.base.diagram
    ranks = {id(finding): rank for rank, finding in enumerate(result.ranked, start=1)}
    review.status, review.error, review.summary, review.cached = result.status, result.error, result.summary, False
    review.diagram = result.diagram
    review.llm_calls, review.input_tokens, review.output_tokens = meter.calls, meter.input_tokens, meter.output_tokens
    review.cost_usd, review.latency_ms = round(meter.cost_usd, 6), meter.latency_ms
    review.findings = [
      ReviewFinding(
        **v.finding.model_dump(),
        status="kept" if v.kept else "dropped",
        drop_reason=v.drop_reason,
        rank=ranks.get(id(v.finding)) if v.kept else None,
        finding_key=finding_key(v.finding),
        original_line=v.original_line,
        replacement_rejected=v.replacement_rejected,
      )
      for v in result.verified
    ] + [
      ReviewFinding(
        **finding.model_dump(),
        status="kept",
        rank=ranks.get(id(finding)),
        finding_key=row.finding_key,
        original_line=row.original_line,
        replacement_rejected=row.replacement_rejected,
        carried_from_review_id=row.carried_from_review_id or plan.base.id,
      )
      for row, finding in zip(carried_rows, carried, strict=True)
    ]
  used = {item.source_id for item in bundle.items if item.kind == "learning"}
  mark_applied([learning for learning in learnings if learning.id in used])
  db.add(review)
  db.commit()
  return review


def _copy_result(review: Review, cached: Review) -> None:
  """Reuse an identical earlier review: same findings and summary, no LLM call, no cost."""
  review.status, review.error, review.summary, review.cached = cached.status, cached.error, cached.summary, True
  review.diagram = cached.diagram
  review.llm_calls = review.input_tokens = review.output_tokens = review.latency_ms = 0
  review.cost_usd = 0.0
  copied = ("path", "line", "severity", "category", "claim", "quote", "suggestion", "confidence",
            "evidence", "status", "drop_reason", "rank", "finding_key", "replacement", "original_line",
            "replacement_rejected", "carried_from_review_id")
  review.findings = [ReviewFinding(**{name: getattr(f, name) for name in copied}) for f in cached.findings]
