"""A short LLM summary of the PR, checked before it is kept.

Length is controlled twice: the prompt asks for at most SUMMARY_MAX_WORDS words, and the
answer is cut at a sentence end if it is longer. Faithfulness check: a summary that names a
file the PR does not change is describing something that is not there, so it is discarded.
"""

import re
from pathlib import PurePosixPath

from app.modules.code.evidence import EvidenceBundle
from app.modules.review.llm import CostMeter
from app.modules.review.prompts import SUMMARY_MAX_WORDS, summary_messages

MAX_OUTPUT_TOKENS = 300
FILE_NAME = re.compile(r"[\w./-]+\.(?:py|js|jsx|ts|tsx|rb|go|java|rs|php|md|toml|json|ya?ml|cfg|txt)\b")


def trim_words(text: str, max_words: int) -> str:
  words = text.split()
  if len(words) <= max_words:
    return " ".join(words)
  cut = " ".join(words[:max_words])
  if cut.endswith((".", "!", "?")):
    return cut
  end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
  return cut[: end + 1] if end > 0 else cut + "..."


def mentions_unknown_files(summary: str, bundle: EvidenceBundle) -> bool:
  changed = {item.path for item in bundle.items if item.path}
  known = changed | {PurePosixPath(path).name for path in changed}
  return any(name not in known and PurePosixPath(name).name not in known for name in FILE_NAME.findall(summary))


def summarize(meter: CostMeter, bundle: EvidenceBundle) -> str | None:
  """The summary, or None when the model's answer failed the faithfulness check."""
  system, user = summary_messages(bundle)
  text = trim_words(meter.complete(system, user, MAX_OUTPUT_TOKENS).text.strip(), SUMMARY_MAX_WORDS)
  if not text or mentions_unknown_files(text, bundle):
    return None
  return text
