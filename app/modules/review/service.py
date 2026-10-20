"""Review a PR: collect evidence, reuse a cached result or run the pipeline, store it all."""

import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.time_utils import utc_now
from app.db.models import PullRequest, PullRequestRisk, Review, ReviewFinding
from app.integrations.github.client import GitHubClient
from app.modules.code.embeddings import Embedder
from app.modules.code.evidence import EvidenceBundle, collect_evidence
from app.modules.review.llm import CostMeter, LLMProvider
from app.modules.review.pipeline import run_pipeline
from app.modules.review.prompts import REVIEW_PROMPT, SUMMARY_PROMPT, review_messages
from app.modules.review.ranking import finding_key

STATUS_COMPLETED = "completed"


def review_cache_key(bundle: EvidenceBundle, model: str) -> str:
  """A hash of the exact model input (prompt version, evidence, model). Same key, same input:
  the stored answer is reused. A new prompt version or a changed diff gives a new key."""
  system, user = review_messages(bundle)
  text = "\0".join([REVIEW_PROMPT, SUMMARY_PROMPT, model, system, user])
  return hashlib.sha256(text.encode()).hexdigest()


async def review_pull_request(
  db: Session,
  github: GitHubClient,
  embedder: Embedder,
  llm: LLMProvider,
  pull_request_id: int,
  *,
  budget_usd: float,
) -> Review:
  pull_request = db.get(PullRequest, pull_request_id)
  if pull_request is None:
    raise ValueError(f"Pull request {pull_request_id} does not exist")
  bundle = await collect_evidence(db, github, embedder, pull_request, budget=settings.review_token_budget)
  key = review_cache_key(bundle, llm.model)
  review = Review(
    pull_request_id=pull_request.id,
    head_sha=pull_request.head_sha,
    prompt_version=REVIEW_PROMPT,
    model=llm.model,
    cache_key=key,
    evidence=bundle.to_json(),
    created_at=utc_now(),
  )

  cached = db.scalars(
    select(Review)
    .where(Review.cache_key == key, Review.status == STATUS_COMPLETED)
    .order_by(Review.id.desc())
    .options(selectinload(Review.findings))
    .limit(1)
  ).first()
  if cached is not None:
    _copy_result(review, cached)
  else:
    risk = db.get(PullRequestRisk, pull_request.id)
    meter = CostMeter(llm, budget_usd)
    result = run_pipeline(meter, bundle, risk.level if risk else None)
    ranks = {finding_key(finding): rank for rank, finding in enumerate(result.ranked, start=1)}
    review.status, review.error, review.summary, review.cached = result.status, result.error, result.summary, False
    review.llm_calls, review.input_tokens, review.output_tokens = meter.calls, meter.input_tokens, meter.output_tokens
    review.cost_usd, review.latency_ms = round(meter.cost_usd, 6), meter.latency_ms
    review.findings = [
      ReviewFinding(
        **v.finding.model_dump(),
        status="kept" if v.kept else "dropped",
        drop_reason=v.drop_reason,
        rank=ranks.get(finding_key(v.finding)) if v.kept else None,
        finding_key=finding_key(v.finding),
      )
      for v in result.verified
    ]
  db.add(review)
  db.commit()
  return review


def _copy_result(review: Review, cached: Review) -> None:
  """Reuse an identical earlier review: same findings and summary, no LLM call, no cost."""
  review.status, review.error, review.summary, review.cached = cached.status, cached.error, cached.summary, True
  review.llm_calls = review.input_tokens = review.output_tokens = review.latency_ms = 0
  review.cost_usd = 0.0
  copied = ("path", "line", "severity", "category", "claim", "quote", "suggestion", "confidence",
            "evidence", "status", "drop_reason", "rank", "finding_key")
  review.findings = [ReviewFinding(**{name: getattr(f, name) for name in copied}) for f in cached.findings]
