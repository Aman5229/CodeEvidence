"""Dedupe, rank and cap the verified findings: a few good comments beat many weak ones.

Priority = severity weight x confidence, x 1.2 when a deterministic signal backs the finding
(two independent sources agree). The PR's risk level sets how many comments it gets: a
risky PR earns more of the reviewer's attention than a routine one.

The repository's review profile (.codeevidence.yaml) sets the tone:
- chill (the default): low-severity findings are left out unless a signal backs them.
- assertive: low severity included, and more comments per PR.
"""

import hashlib

from app.modules.review.findings import Finding

SEVERITY_WEIGHT = {"high": 3.0, "medium": 2.0, "low": 1.0}
SIGNAL_BOOST = 1.2
MAX_COMMENTS = {"high": 5, "medium": 3, "low": 3}  # chill
ASSERTIVE_MAX_COMMENTS = {"high": 8, "medium": 6, "low": 5}
NEARBY_LINES = 3  # same file, same category, this close: the same problem


def signal_backed(finding: Finding, signal_ids: set[str] | None = None) -> bool:
  """Whether a cited evidence item is a signal. Without `signal_ids`, signals are the S ids."""
  if signal_ids is None:
    return any(item_id.startswith("S") for item_id in finding.evidence)
  return any(item_id in signal_ids for item_id in finding.evidence)


def priority(finding: Finding, signal_ids: set[str] | None = None) -> float:
  boost = SIGNAL_BOOST if signal_backed(finding, signal_ids) else 1.0
  return SEVERITY_WEIGHT[finding.severity] * finding.confidence * boost


def finding_key(finding: Finding) -> str:
  """Stable across runs: the same problem on the same code gets the same key, even if the
  model words the claim differently or the line moves."""
  text = f"{finding.path}|{finding.category}|{' '.join(finding.quote.split())}"
  return hashlib.sha256(text.encode()).hexdigest()[:32]


def rank_findings(
  findings: list[Finding], risk_level: str | None, profile: str = "chill", signal_ids: set[str] | None = None
) -> list[Finding]:
  """Best first, duplicates removed, at most the profile's cap for the PR's risk level.

  Ties are broken by path, line and claim, so the same input always gives the same order.
  `signal_ids` names the evidence items that are signals when ids alone do not tell (findings
  carried over from an earlier review cite renumbered items).
  """
  if profile == "chill":
    findings = [f for f in findings if f.severity != "low" or signal_backed(f, signal_ids)]
  ordered = sorted(findings, key=lambda f: (-priority(f, signal_ids), f.path, f.line, f.claim))
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
  caps = ASSERTIVE_MAX_COMMENTS if profile == "assertive" else MAX_COMMENTS
  return kept[: caps.get(risk_level or "low", caps["low"])]
