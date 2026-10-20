"""Dedupe, rank and cap the verified findings: a few good comments beat many weak ones.

Priority = severity weight x confidence, x 1.2 when a deterministic signal backs the finding
(two independent sources agree). The PR's risk level sets how many comments it gets: a
risky PR earns more of the reviewer's attention than a routine one.
"""

import hashlib

from app.modules.review.findings import Finding

SEVERITY_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}
SIGNAL_BOOST = 1.2
MAX_COMMENTS = {"high": 5, "medium": 3, "low": 3}
NEARBY_LINES = 3  # same file, same category, this close: the same problem


def priority(finding: Finding) -> float:
  boost = SIGNAL_BOOST if any(item_id.startswith("S") for item_id in finding.evidence) else 1.0
  return SEVERITY_WEIGHT[finding.severity] * finding.confidence * boost


def finding_key(finding: Finding) -> str:
  """Stable across runs: the same problem on the same code gets the same key, even if the
  model words the claim differently or the line moves."""
  text = f"{finding.path}|{finding.category}|{' '.join(finding.quote.split())}"
  return hashlib.sha256(text.encode()).hexdigest()[:32]


def rank_findings(findings: list[Finding], risk_level: str | None) -> list[Finding]:
  """Best first, duplicates removed, at most MAX_COMMENTS for the PR's risk level.

  Ties are broken by path, line and claim, so the same input always gives the same order.
  """
  ordered = sorted(findings, key=lambda f: (-priority(f), f.path, f.line, f.claim))
  kept: list[Finding] = []
  for finding in ordered:
    duplicate = any(
      other.path == finding.path
      and other.category == finding.category
      and abs(other.line - finding.line) <= NEARBY_LINES
      for other in kept
    )
    if not duplicate:
      kept.append(finding)
  return kept[: MAX_COMMENTS.get(risk_level or "low", 3)]
