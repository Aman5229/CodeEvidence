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

import ast
import textwrap
from dataclasses import dataclass

from app.modules.code.diff import parse_patch
from app.modules.code.evidence import EvidenceBundle
from app.modules.review.findings import Finding

MIN_CONFIDENCE = 0.5
INVALID_ID_PENALTY = 0.8  # confidence multiplier when some cited ids do not exist
MAX_REPLACEMENT_LINES = 20
# Models sometimes write "no fix" as text instead of JSON null: never code for the line
PLACEHOLDERS = {"null", "none", "nil", "undefined", "n/a", "na", "-", "...", "same", "unchanged", "no change"}


@dataclass(frozen=True)
class Verified:
  finding: Finding  # possibly corrected: line, evidence ids, confidence, replacement
  kept: bool
  drop_reason: str | None
  original_line: str | None = None  # the added line the finding points at
  replacement_rejected: str | None = None  # why a proposed one-click fix was refused


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

  hunk_id, original_line = added[line]
  evidence = valid_ids if hunk_id in valid_ids else [hunk_id, *valid_ids]
  replacement, rejected = check_replacement(finding.replacement, original_line, finding.path, line, bundle)
  corrected = finding.model_copy(
    update={"line": line, "evidence": evidence, "confidence": round(confidence, 3), "replacement": replacement}
  )
  if confidence < MIN_CONFIDENCE:
    return Verified(corrected, False, "low_confidence", original_line, rejected)
  return Verified(corrected, True, None, original_line, rejected)


def check_replacement(
  replacement: str | None, original: str, path: str, line: int, bundle: EvidenceBundle
) -> tuple[str | None, str | None]:
  """A proposed one-click fix: (the fix to keep, or None; why it was refused, or None).

  Refused when it is not a plain code edit, changes nothing, is long, or (for Python) would
  stop the enclosing function from parsing. "null" or "none" written as text means no fix. A
  fix that lost the line's indentation gets it back: the most common slip of a model, and
  harmless to correct.
  """
  if replacement is None or replacement.strip().strip("\"'`").lower() in PLACEHOLDERS | {""}:
    return None, None  # no fix proposed
  replacement = replacement.rstrip("\n")
  if "```" in replacement:
    return None, "markdown_fence"
  if " ".join(replacement.split()) == " ".join(original.split()):
    return None, "no_change"
  if replacement.count("\n") + 1 > MAX_REPLACEMENT_LINES:
    return None, "too_long"
  indent = original[: len(original) - len(original.lstrip())]
  if indent and not replacement[:1].isspace():
    replacement = textwrap.indent(replacement, indent)
  if path.endswith(".py") and not _still_parses(replacement, path, line, bundle):
    return None, "syntax_error"
  return replacement, None


def _still_parses(replacement: str, path: str, line: int, bundle: EvidenceBundle) -> bool:
  """Put the fix into the function around the line and parse it, when that function is in the
  evidence and parsed before. Without it, nothing can be checked: the fix is kept."""
  function = next(
    (
      item for item in bundle.items
      if item.kind == "function" and item.path == path and item.start_line is not None
      and item.start_line <= line <= (item.end_line or item.start_line)
    ),
    None,
  )
  if function is None:
    return True
  lines = function.text.splitlines()
  index = line - function.start_line
  if not 0 <= index < len(lines) or not _parses("\n".join(lines)):
    return True
  return _parses("\n".join([*lines[:index], *replacement.splitlines(), *lines[index + 1 :]]))


def _parses(code: str) -> bool:
  try:
    ast.parse(textwrap.dedent(code))
  except SyntaxError:
    return False
  return True
