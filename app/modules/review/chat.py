"""Ask CodeEvidence: questions about a PR, answered from its evidence, with citations.

The context is the PR's latest review evidence (or, before any review, its diff and rule
signals), plus code found in the repository for the question itself (ids Q1, Q2...). The
answer must cite evidence ids; cited ids that do not exist are reported, never shown as links.

On GitHub, a comment mentioning @codeevidence is a command (review, full review, remember,
help) or a question. Only people who can write to the repository may use them: each one can
cost a model call. Our own comments carry a hidden marker and are never answered, so the bot
cannot talk to itself.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.time_utils import utc_now
from app.db.models import ChatMessage, CodeChunk, PullRequest, Repository, Review
from app.modules.code.embeddings import Embedder
from app.modules.code.evidence import (
  EvidenceBundle,
  EvidenceItem,
  build_bundle,
  estimate_tokens,
  reviewable_files,
)
from app.modules.code.retrieval import retrieve
from app.modules.code.signals import detect_signals
from app.modules.review.llm import CostMeter, LLMResponse, Messages, cost_usd
from app.modules.review.prompts import data_tag, load_prompt, render_bundle

CHAT_PROMPT = "chat_v1"
MAX_ANSWER_WORDS = 180
MAX_OUTPUT_TOKENS = 900
HISTORY_TURNS = 6  # earlier messages sent along: enough for follow-ups, bounded in cost
MAX_HISTORY_CHARS = 2000
QUESTION_MATCHES = 4
# When the evidence is over budget, the least important kinds go first
KEEP_ORDER = ("signal", "learning", "instruction", "hunk", "question", "guideline", "function", "related")
CITATION = re.compile(r"\[([A-Z]\d{1,3})\]")
MENTION = re.compile(r"@codeevidence\b", re.IGNORECASE)
OWN_MARKER = "<!-- codeevidence"
COMMENT_EVENTS = {"issue_comment", "pull_request_review_comment"}
# Commands cost money (model calls): only people who can write to the repository may use them
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


@dataclass(frozen=True)
class ChatAnswer:
  text: str
  citations: list[str]  # cited ids that exist in the evidence
  unknown_citations: list[str]  # cited ids that do not: the model made them up
  response: LLMResponse


@dataclass(frozen=True)
class Mention:
  command: str  # ask, review, full_review, remember, help
  text: str


# ---------- context ----------

def chat_bundle(db: Session, embedder: Embedder, pull_request: PullRequest, question: str, budget: int) -> EvidenceBundle:
  review = db.scalars(
    select(Review).where(Review.pull_request_id == pull_request.id).order_by(Review.created_at.desc(), Review.id.desc()).limit(1)
  ).first()
  if review is not None:
    bundle = EvidenceBundle.from_json(pull_request.title, pull_request.body or "", review.evidence)
  else:
    files, _ = reviewable_files(db, pull_request, [])
    bundle = build_bundle(pull_request.title, pull_request.body or "", files, detect_signals(files), {}, {}, budget)

  if db.scalar(select(exists().where(CodeChunk.repository_id == pull_request.repository_id))):
    present = {(item.path, item.start_line) for item in bundle.items}
    found = [
      chunk for chunk in retrieve(db, embedder, pull_request.repository_id, question, k=QUESTION_MATCHES)
      if (chunk.path, chunk.start_line) not in present
    ]
    bundle.items.extend(
      EvidenceItem(f"Q{number}", "question", chunk.path, chunk.start_line, chunk.end_line, chunk.content)
      for number, chunk in enumerate(found, start=1)
    )
  return fit_to_budget(bundle, budget)


def fit_to_budget(bundle: EvidenceBundle, budget: int) -> EvidenceBundle:
  """Drop the least important evidence until the bundle fits the budget."""
  rank = {kind: index for index, kind in enumerate(KEEP_ORDER)}
  items = sorted(bundle.items, key=lambda item: rank.get(item.kind, len(KEEP_ORDER)))
  kept = EvidenceBundle(bundle.title, bundle.description, budget=budget)
  used = estimate_tokens(bundle.title) + estimate_tokens(bundle.description)
  for item in items:
    cost = estimate_tokens(item.text)
    if used + cost <= budget:
      kept.items.append(item)
      used += cost
    else:
      kept.dropped += 1
  original_order = {item.id: index for index, item in enumerate(bundle.items)}
  kept.items.sort(key=lambda item: original_order[item.id])
  return kept


def history(db: Session, pull_request_id: int) -> list[ChatMessage]:
  rows = db.scalars(
    select(ChatMessage).where(ChatMessage.pull_request_id == pull_request_id).order_by(ChatMessage.id.desc()).limit(HISTORY_TURNS)
  ).all()
  return list(reversed(rows))


def chat_messages(bundle: EvidenceBundle, earlier: list[ChatMessage], question: str) -> tuple[str, Messages]:
  tag = data_tag(bundle)
  system = load_prompt(CHAT_PROMPT).replace("{tag}", tag).replace("{max_words}", str(MAX_ANSWER_WORDS))
  messages: Messages = [{"role": message.role, "content": message.content[:MAX_HISTORY_CHARS]} for message in earlier]
  messages.append({"role": "user", "content": f"{render_bundle(bundle, tag)}\n\nQuestion: {question}"})
  return system, _alternating(messages)


def _alternating(messages: Messages) -> Messages:
  """Providers want user and assistant turns to alternate: merge any two in a row."""
  merged: Messages = []
  for message in messages:
    if merged and merged[-1]["role"] == message["role"]:
      merged[-1] = {"role": message["role"], "content": merged[-1]["content"] + "\n\n" + message["content"]}
    else:
      merged.append(dict(message))
  while merged and merged[0]["role"] != "user":
    merged.pop(0)
  return merged


# ---------- answering ----------

def extract_citations(text: str, bundle: EvidenceBundle) -> tuple[list[str], list[str]]:
  cited = list(dict.fromkeys(CITATION.findall(text)))
  return [item for item in cited if bundle.get(item)], [item for item in cited if not bundle.get(item)]


def stream_answer(meter: CostMeter, bundle: EvidenceBundle, earlier: list[ChatMessage], question: str) -> Iterator[str | ChatAnswer]:
  """Pieces of the answer as they arrive, then the ChatAnswer with its citations and cost."""
  system, messages = chat_messages(bundle, earlier, question)
  final: LLMResponse | None = None
  for chunk in meter.stream(system, messages, MAX_OUTPUT_TOKENS):
    if isinstance(chunk, LLMResponse):
      final = chunk
    else:
      yield chunk
  if final is None:
    raise RuntimeError("The model stream ended without a final message")
  citations, unknown = extract_citations(final.text, bundle)
  yield ChatAnswer(final.text, citations, unknown, final)


def answer(meter: CostMeter, bundle: EvidenceBundle, earlier: list[ChatMessage], question: str) -> ChatAnswer:
  """The whole answer at once (GitHub replies)."""
  result = None
  for chunk in stream_answer(meter, bundle, earlier, question):
    if isinstance(chunk, ChatAnswer):
      result = chunk
  return result


def citation_details(ids: list[str], bundle: EvidenceBundle) -> list[dict]:
  """Where each cited item is, stored with the answer: the evidence itself is not kept."""
  items = [bundle.get(item_id) for item_id in ids]
  return [
    {"id": item.id, "kind": item.kind, "path": item.path, "start_line": item.start_line, "end_line": item.end_line}
    for item in items
    if item is not None
  ]


def save_exchange(
  db: Session,
  pull_request_id: int,
  question: str,
  result: ChatAnswer,
  bundle: EvidenceBundle,
  *,
  source: str,
  model: str,
  github_user: str | None = None,
  github_comment_id: int | None = None,
) -> tuple[ChatMessage, ChatMessage]:
  """Store a question and its answer, with the answer's citations and cost."""
  now = utc_now()
  response = result.response
  asked = ChatMessage(
    pull_request_id=pull_request_id, role="user", content=question, citations=[], source=source,
    github_user=github_user, github_comment_id=github_comment_id, created_at=now,
  )
  answered = ChatMessage(
    pull_request_id=pull_request_id, role="assistant", content=result.text,
    citations=citation_details(result.citations, bundle), source=source, github_comment_id=github_comment_id,
    model=model, input_tokens=response.input_tokens, output_tokens=response.output_tokens,
    cost_usd=round(cost_usd(response.input_tokens, response.output_tokens), 6), latency_ms=response.latency_ms,
    created_at=now,
  )
  db.add_all([asked, answered])
  db.flush()
  return asked, answered


# ---------- GitHub mentions ----------

def is_own_comment(body: str | None) -> bool:
  return OWN_MARKER in (body or "")


def parse_mention(body: str | None) -> Mention | None:
  """The command in a comment that mentions @codeevidence, or None."""
  if not body or is_own_comment(body):
    return None
  match = MENTION.search(body)
  if match is None:
    return None
  text = body[match.end():].strip()
  words = text.split()
  first = words[0].lower().rstrip(".:,!") if words else ""
  if not text or first == "help":
    return Mention("help", "")
  if text.lower().startswith("full review"):
    return Mention("full_review", "")
  if first == "review":
    return Mention("review", "")
  if first in ("remember", "learn"):
    return Mention("remember", text[len(words[0]):].strip(" :"))
  return Mention("ask", text)


def render_for_github(text: str, bundle: EvidenceBundle) -> str:
  """Citations as `path:lines` (or the evidence kind) instead of ids nobody on GitHub can see."""

  def replace(match: re.Match) -> str:
    item = bundle.get(match.group(1))
    if item is None:
      return ""  # made up by the model: dropped
    if item.path and item.start_line is not None:
      return f" (`{item.path}:{item.start_line}-{item.end_line}`)"
    return f" ({item.kind}: `{item.path}`)" if item.path else ""

  return CITATION.sub(replace, text).replace("  ", " ")


HELP_TEXT = """**CodeEvidence commands** (write them after @codeevidence):
- `review`: review the changes since the last review
- `full review`: review the whole pull request again
- `remember <rule>`: propose a rule for future reviews of this repository (it is approved in the dashboard)
- anything else: a question about this pull request, answered from its code, with sources"""


def answer_marker(comment_id: int) -> str:
  """Hidden in each reply: marks it as ours, and names the comment it answers (never twice)."""
  return f"{OWN_MARKER}:answer:{comment_id} -->"


def github_reply(body: str, dashboard_link: str, comment_id: int) -> str:
  return f"{body}\n\n<sub>CodeEvidence · [open in the dashboard]({dashboard_link})</sub>\n{answer_marker(comment_id)}"


@dataclass(frozen=True)
class PullRequestComment:
  """A new comment on a PR, from an `issue_comment` or `pull_request_review_comment` webhook."""

  pull_request_id: int
  comment_id: int
  kind: str  # issue (the conversation), review (an inline thread)
  body: str
  author: str | None
  trusted: bool  # the author can write to the repository
  in_reply_to_id: int | None  # review threads: the comment that started the thread


def comment_from_event(db: Session, event_type: str, payload: dict) -> PullRequestComment | None:
  """The new PR comment an event carries, or None (another event, an edit, a plain issue, a PR
  we do not know)."""
  if payload.get("action") != "created" or event_type not in COMMENT_EVENTS:
    return None
  comment = payload.get("comment") or {}
  if event_type == "issue_comment":
    issue = payload.get("issue") or {}
    if not issue.get("pull_request"):
      return None  # a comment on an issue, not a pull request
    number = issue.get("number")
  else:
    number = (payload.get("pull_request") or {}).get("number")
  repository_id = (payload.get("repository") or {}).get("id")
  pull_request = db.scalars(
    select(PullRequest)
    .join(Repository, Repository.id == PullRequest.repository_id)
    .where(Repository.github_repo_id == repository_id, PullRequest.number == number)
  ).first()
  if pull_request is None or comment.get("id") is None:
    return None
  return PullRequestComment(
    pull_request_id=pull_request.id,
    comment_id=comment["id"],
    kind="issue" if event_type == "issue_comment" else "review",
    body=comment.get("body") or "",
    author=(comment.get("user") or {}).get("login"),
    trusted=comment.get("author_association") in TRUSTED_ASSOCIATIONS,
    in_reply_to_id=comment.get("in_reply_to_id"),
  )
