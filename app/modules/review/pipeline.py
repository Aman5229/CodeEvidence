"""The review itself, without the database: evidence in, verified and ranked findings out.

Kept free of I/O so the evaluation in CI can replay recorded model answers through exactly
the code that runs in production.
"""

from dataclasses import dataclass, field

from app.modules.code.evidence import EvidenceBundle
from app.modules.review.findings import Finding, findings_with_repair
from app.modules.review.llm import BudgetExceeded, CostMeter
from app.modules.review.prompts import review_messages
from app.modules.review.ranking import rank_findings
from app.modules.review.summary import summarize
from app.modules.review.verification import Verified, verify

MAX_OUTPUT_TOKENS = 2000


@dataclass
class PipelineResult:
  status: str  # completed, budget_exceeded
  error: str | None = None
  summary: str | None = None
  verified: list[Verified] = field(default_factory=list)  # every proposed finding, kept or dropped
  ranked: list[Finding] = field(default_factory=list)  # the ones to show, best first


def run_pipeline(meter: CostMeter, bundle: EvidenceBundle, risk_level: str | None, *, with_summary: bool = True) -> PipelineResult:
  result = PipelineResult(status="completed")
  system, user = review_messages(bundle)
  proposed: list[Finding] = []
  try:
    proposed, result.error = findings_with_repair(meter, system, user, MAX_OUTPUT_TOKENS)
    if with_summary:  # after the findings: if money runs out, the findings matter more
      result.summary = summarize(meter, bundle)
  except BudgetExceeded as error:
    result.status, result.error = "budget_exceeded", str(error)
  result.verified = [verify(finding, bundle) for finding in proposed]
  result.ranked = rank_findings([v.finding for v in result.verified if v.kept], risk_level)
  return result
