"""Verification: a finding survives only if the evidence it cites really supports it.

Plain checks, no second LLM call, run in this order:
1. At least one cited evidence id exists. Ids that do not exist are removed, and the
   finding's confidence is lowered: it cited things that are not there.
2. The finding points at a line that this PR added, in a file this PR changed. GitHub can
   only show inline comments on diff lines, and a comment about unchanged code is not
   about this PR.
3. The quoted code appears on that line. A model that is off by a line or two is corrected
   when the quote matches another added line of the same file; a quote that matches no
   added line means the finding talks about code that does not exist: dropped.
4. Confidence of at least MIN_CONFIDENCE, after the adjustments above.
"""

from dataclasses import dataclass

from app.modules.code.diff import parse_patch
from app.modules.code.evidence import EvidenceBundle
from app.modules.review.findings import Finding

MIN_CONFIDENCE = 0.5
INVALID_ID_PENALTY = 0.8  # confidence multiplier when some cited ids do not exist


@dataclass(frozen=True)
class Verified:
  finding: Finding  # possibly corrected: line, evidence ids, confidence
  kept: bool
  drop_reason: str | None


def _normalize(text: str) -> str:
  return " ".join(text.split())


def added_lines(bundle: EvidenceBundle, path: str) -> dict[int, tuple[str, str]]:
  """{new line number: (hunk id, line text)} for every line the PR added to `path`."""
  lines = {}
  for item in bundle.items:
    if item.kind == "hunk" and item.path == path:
      for hunk in parse_patch(item.text):
        for line in hunk.added:
          lines[line.new_line] = (item.id, line.text)
  return lines


def verify(finding: Finding, bundle: EvidenceBundle) -> Verified:
  valid_ids = [item_id for item_id in finding.evidence if bundle.get(item_id) is not None]
  if not valid_ids:
    return Verified(finding, False, "no_valid_evidence")
  confidence = finding.confidence * (INVALID_ID_PENALTY if len(valid_ids) < len(finding.evidence) else 1.0)

  added = added_lines(bundle, finding.path)
  if not added:
    return Verified(finding, False, "path_not_in_diff")

  quote = _normalize(finding.quote)
  line = finding.line
  if line not in added or quote not in _normalize(added[line][1]):
    matches = [number for number, (_, text) in added.items() if quote and quote in _normalize(text)]
    if not matches:
      reason = "line_not_in_diff" if line not in added else "quote_not_found"
      return Verified(finding, False, reason)
    line = min(matches, key=lambda number: (abs(number - finding.line), number))  # the nearest one

  hunk_id = added[line][0]
  evidence = valid_ids if hunk_id in valid_ids else [hunk_id, *valid_ids]
  corrected = finding.model_copy(update={"line": line, "evidence": evidence, "confidence": round(confidence, 3)})
  if confidence < MIN_CONFIDENCE:
    return Verified(corrected, False, "low_confidence")
  return Verified(corrected, True, None)
