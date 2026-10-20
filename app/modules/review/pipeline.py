"""The review itself, without the database: evidence in, verified and ranked findings out.

Kept free of I/O so the evaluation in CI can replay recorded model answers through exactly
the code that runs in production.

Model calls, in order: the findings (plus one repair if needed), the summary, the diagram.
If money runs out, what matters most has already been done. The diagram is optional: when it
cannot be made (budget, a failing model), the review is still complete without it.
"""

import logging
from dataclasses import dataclass, field

from app.modules.code.evidence import EvidenceBundle, EvidenceItem
from app.modules.review.diagram import make_diagram
from app.modules.review.findings import Finding, findings_with_repair
from app.modules.review.llm import BudgetExceeded, CostMeter, LLMError
from app.modules.review.prompts import review_messages
from app.modules.review.ranking import rank_findings
from app.modules.review.summary import summarize
from app.modules.review.verification import Verified, verify

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 2000


@dataclass
class PipelineResult:
  status: str  # completed, budget_exceeded
  error: str | None = None
  summary: str | None = None
  diagram: str | None = None  # Mermaid sequence diagram, when one passed its checks
  verified: list[Verified] = field(default_factory=list)  # every proposed finding, kept or dropped
  ranked: list[Finding] = field(default_factory=list)  # the ones to show, best first


def run_pipeline(
  meter: CostMeter,
  bundle: EvidenceBundle,
  risk_level: str | None,
  *,
  with_summary: bool = True,
  summary_bundle: EvidenceBundle | None = None,
  profile: str = "chill",
  with_diagram: bool = False,
  carried: list[Finding] = (),
  carried_evidence: list[EvidenceItem] = (),
) -> PipelineResult:
  """`summary_bundle` covers the whole PR when `bundle` holds only part of it (an incremental
  review). `carried` are findings kept from an earlier review: they compete with the new ones
  for the same places, and `carried_evidence` holds the items they cite."""
  result = PipelineResult(status="completed")
  whole = summary_bundle or bundle
  proposed: list[Finding] = []
  try:
    if any(item.kind == "hunk" for item in bundle.items):  # nothing changed to review: no call
      system, user = review_messages(bundle)
      proposed, result.error = findings_with_repair(meter, system, user, MAX_OUTPUT_TOKENS)
    if with_summary:
      result.summary = summarize(meter, whole)
  except BudgetExceeded as error:
    result.status, result.error = "budget_exceeded", str(error)
  if with_diagram and result.status == "completed":
    try:
      result.diagram = make_diagram(meter, whole)
    except (BudgetExceeded, LLMError) as error:
      logger.warning("No diagram: %s", error)
  result.verified = [verify(finding, bundle) for finding in proposed]
  signal_ids = {item.id for item in [*bundle.items, *carried_evidence] if item.kind == "signal"}
  kept = [v.finding for v in result.verified if v.kept]
  result.ranked = rank_findings([*kept, *carried], risk_level, profile, signal_ids)
  return result
