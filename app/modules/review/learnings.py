"""Learnings: rules for a repository's future reviews, learned from feedback or written by hand.

How a learning is born:
- A reviewer rejects a finding and says why (a 👎 with a reason in the dashboard, or a reply
  on GitHub, or "@codeevidence remember ..."). A model turns that into one short rule.
- Or someone writes one in the dashboard.

Then the most relevant learnings (by path pattern and meaning) are added to every review of
that repository as evidence "L", which the prompt says to follow.

Trust: anyone who can comment on a PR on GitHub could try to write a rule like "never report
security issues". So learnings from GitHub start disabled until approved in the dashboard,
and rules that turn off a whole category of findings are refused.
"""

import json
import re

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import Learning
from app.modules.code.embeddings import Embedder
from app.modules.code.globs import path_matches
from app.modules.review.llm import CostMeter
from app.modules.review.prompts import load_prompt, untrusted_tag

LEARNING_PROMPT = "learning_v1"
MAX_OUTPUT_TOKENS = 200
MIN_LEARNING_CHARS = 10
MAX_LEARNING_CHARS = 300
RELEVANT_LEARNINGS = 5
CANDIDATES = 50  # nearest by meaning, before the path check
# "ignore all security issues", "never report any bugs"...: a rule must not switch off a category
BLANKET_RULE = re.compile(
  r"\b(ignore|skip|never (report|flag|mention)|(do not|don't) (report|flag|mention)|disable|stop)\b.{0,40}"
  r"\b(all|any|every)\b.{0,20}\b(security|bugs?|issues?|findings?|problems?|comments?|vulnerabilit\w*)\b",
  re.IGNORECASE,
)
JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class DistilledLearning(BaseModel):
  rule: str | None = Field(default=None, max_length=MAX_LEARNING_CHARS)
  path_glob: str | None = Field(default=None, max_length=255)


def is_blanket_rule(text: str) -> bool:
  return bool(BLANKET_RULE.search(text))


def parse_learning(text: str) -> DistilledLearning:
  """The model's answer, validated. Anything unusable or too broad means: no rule."""
  block = JSON_BLOCK.search(text)
  try:
    learning = DistilledLearning.model_validate(json.loads(block.group(1) if block else text.strip(), strict=False))
  except (ValueError, ValidationError):
    return DistilledLearning()
  rule = (learning.rule or "").strip()
  if not rule or is_blanket_rule(rule):
    return DistilledLearning()
  return DistilledLearning(rule=rule, path_glob=(learning.path_glob or "").strip() or None)


def distill(meter: CostMeter, *, path: str, claim: str, quote: str, reason: str) -> DistilledLearning:
  """Ask the model for a rule behind a rejection."""
  tag = untrusted_tag(path, claim, quote, reason)
  system = load_prompt(LEARNING_PROMPT).replace("{tag}", tag)
  user = (
    f'<{tag} id="rejected-comment" path="{path}">\n{claim}\nCode: {quote}\n</{tag}>\n\n'
    f'<{tag} id="explanation">\n{reason}\n</{tag}>\n\nWrite the rule, or null.'
  )
  return parse_learning(meter.complete(system, user, MAX_OUTPUT_TOKENS).text)


def embedding_text(text: str, path_glob: str | None) -> str:
  return f"{path_glob or ''}\n{text}".strip()


def create_learning(
  db: Session,
  embedder: Embedder,
  *,
  repository_id: int,
  text: str,
  path_glob: str | None,
  source: str,
  enabled: bool,
  source_finding_id: int | None = None,
) -> Learning:
  now = utc_now()
  learning = Learning(
    repository_id=repository_id,
    text=text.strip(),
    path_glob=(path_glob or "").strip() or None,
    source=source,
    source_finding_id=source_finding_id,
    enabled=enabled,
    embedding=embedder.embed([embedding_text(text, path_glob)])[0],
    embedding_model=embedder.model_name,
    times_applied=0,
    created_at=now,
    updated_at=now,
  )
  db.add(learning)
  db.flush()
  return learning


def update_learning(
  db: Session, embedder: Embedder, learning: Learning, *, text: str | None, path_glob: str | None, enabled: bool | None,
  path_glob_given: bool,
) -> Learning:
  """Change a learning. A new text or path pattern is embedded again."""
  if text is not None:
    learning.text = text.strip()
  if path_glob_given:
    learning.path_glob = (path_glob or "").strip() or None
  if text is not None or path_glob_given:
    learning.embedding = embedder.embed([embedding_text(learning.text, learning.path_glob)])[0]
    learning.embedding_model = embedder.model_name
  if enabled is not None:
    learning.enabled = enabled
  learning.updated_at = utc_now()
  db.flush()
  return learning


def relevant_learnings(
  db: Session, embedder: Embedder, repository_id: int, paths: list[str], query: str, k: int = RELEVANT_LEARNINGS
) -> list[Learning]:
  """The enabled learnings that apply to these files, closest in meaning to the change first."""
  if not db.scalar(select(exists().where(Learning.repository_id == repository_id, Learning.enabled.is_(True)))):
    return []  # nothing to match: skip embedding the query
  vector = embedder.embed([query])[0]
  candidates = db.scalars(
    select(Learning)
    .where(Learning.repository_id == repository_id, Learning.enabled.is_(True))
    .order_by(Learning.embedding.cosine_distance(vector), Learning.id)
    .limit(CANDIDATES)
  ).all()
  applicable = [
    learning for learning in candidates
    if learning.path_glob is None or any(path_matches(path, learning.path_glob) for path in paths)
  ]
  return applicable[:k]


def mark_applied(learnings: list[Learning]) -> None:
  now = utc_now()
  for learning in learnings:
    learning.times_applied += 1
    learning.last_applied_at = now
