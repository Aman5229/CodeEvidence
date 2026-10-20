"""The shape of a review finding, and turning the model's text into validated findings.

The model is asked for JSON. Its answer is validated against this schema. If that fails,
the error is sent back once ("repair") and the model gets one more try; after that the
review continues with no findings rather than with made-up ones.
"""

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.modules.review.llm import CostMeter

MAX_FINDINGS = 10  # per answer; more is noise, and it bounds the output tokens


class Finding(BaseModel):
  path: str
  line: int = Field(ge=1)  # line in the new version of the file
  severity: Literal["low", "medium", "high"]
  category: Literal["bug", "security", "performance", "maintainability", "tests"]
  claim: str = Field(min_length=10, max_length=600)
  quote: str = Field(min_length=1, max_length=400)  # code copied exactly from the cited evidence
  evidence: list[str] = Field(min_length=1, max_length=5)  # ids such as H1, F2, S1
  suggestion: str | None = Field(default=None, max_length=800)
  # The complete new text of `line` when a local edit fixes it (a one-click fix on GitHub)
  replacement: str | None = Field(default=None, max_length=2000)
  confidence: float = Field(ge=0, le=1)


class FindingsAnswer(BaseModel):
  findings: list[Finding] = Field(max_length=MAX_FINDINGS)


JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

REPAIR_PROMPT = """Your previous answer could not be used:

{error}

Answer again with only the corrected JSON object, nothing else. Previous answer:

{answer}"""


def parse_findings(text: str) -> FindingsAnswer:
  """Validate an answer. Accepts bare JSON or JSON inside a ```json block. Line breaks typed
  inside a string are accepted too (strict=False): models write a multi-line replacement that
  way, and refusing it would lose every finding of the answer."""
  block = JSON_BLOCK.search(text)
  return FindingsAnswer.model_validate(json.loads(block.group(1) if block else text.strip(), strict=False))


def findings_with_repair(meter: CostMeter, system: str, user: str, max_tokens: int) -> tuple[list[Finding], str | None]:
  """Ask, validate, and repair once if needed. Returns (findings, error if still invalid)."""
  answer = meter.complete(system, user, max_tokens).text
  try:
    return parse_findings(answer).findings, None
  except (ValueError, ValidationError) as error:
    problem = _describe(error)
  repaired = meter.complete(system, REPAIR_PROMPT.format(error=problem, answer=answer[:4000]), max_tokens).text
  try:
    return parse_findings(repaired).findings, None
  except (ValueError, ValidationError) as error:
    return [], f"Invalid answer after one repair: {_describe(error)}"


def _describe(error: Exception) -> str:
  if isinstance(error, ValidationError):
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()[:10])
  return f"Not valid JSON: {error}"
