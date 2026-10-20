"""The evidence bundle: everything the reviewer may look at for one PR, trimmed to a budget.

Each item has an id the LLM must cite (H = a diff hunk, F = the full function around a hunk,
R = related code found by retrieval, S = a deterministic signal). The verifier later checks
that cited ids exist, so a finding can only stand on evidence that is really there.

When everything does not fit the token budget, items are kept in order of importance:
signals (short, certain), then hunks (the change itself), then enclosing functions, then
related code (best match of each hunk first).
"""

from dataclasses import asdict, dataclass, field

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import CodeChunk, PullRequest, PullRequestFile, Repository
from app.integrations.github.client import GitHubClient
from app.modules.code.chunking import chunk_file
from app.modules.code.contents import get_file_text
from app.modules.code.diff import parse_patch
from app.modules.code.embeddings import Embedder
from app.modules.code.filters import detect_language, skip_reason
from app.modules.code.retrieval import RetrievedChunk, retrieve
from app.modules.code.signals import FileDiff, Signal, detect_signals

DEFAULT_TOKEN_BUDGET = 12_000
MAX_DESCRIPTION_TOKENS = 400
RETRIEVED_PER_HUNK = 3
MAX_RETRIEVAL_HUNKS = 30  # retrieval is one search per hunk; huge PRs only get it for the first ones


def estimate_tokens(text: str) -> int:
  """About 4 characters per token for English and code. Good enough for budgeting; the
  provider reports exact counts after the call."""
  return len(text) // 4 + 1


@dataclass(frozen=True)
class EvidenceItem:
  id: str
  kind: str  # hunk, function, related, signal
  path: str | None
  start_line: int | None
  end_line: int | None
  text: str
  new_lines: tuple[int, ...] = ()  # hunks only: the new-file lines a comment may point at


@dataclass
class EvidenceBundle:
  title: str
  description: str
  items: list[EvidenceItem] = field(default_factory=list)
  dropped: int = 0  # items left out to stay within the budget
  budget: int = DEFAULT_TOKEN_BUDGET

  @property
  def tokens(self) -> int:
    return estimate_tokens(self.title) + estimate_tokens(self.description) + sum(
      estimate_tokens(item.text) for item in self.items
    )

  def get(self, item_id: str) -> EvidenceItem | None:
    return next((item for item in self.items if item.id == item_id), None)

  def to_json(self) -> list[dict]:
    return [asdict(item) for item in self.items]

  @classmethod
  def from_json(cls, title: str, description: str, items: list[dict]) -> "EvidenceBundle":
    """Rebuild a stored bundle (e.g. a recorded evaluation case)."""
    return cls(
      title=title,
      description=description,
      items=[EvidenceItem(**{**item, "new_lines": tuple(item.get("new_lines", ()))}) for item in items],
    )


def build_bundle(
  title: str,
  description: str,
  files: list[FileDiff],
  signals: list[Signal],
  functions: dict[tuple[str, int], list[tuple[int, int, str]]],
  related: dict[tuple[str, int], list[RetrievedChunk]],
  budget: int = DEFAULT_TOKEN_BUDGET,
) -> EvidenceBundle:
  """`functions` and `related` are keyed by (path, hunk index). Functions are (start, end, text)."""
  description = description[: MAX_DESCRIPTION_TOKENS * 4]
  bundle = EvidenceBundle(title=title, description=description, budget=budget)
  remaining = budget - estimate_tokens(title) - estimate_tokens(description)

  candidates: list[EvidenceItem] = []
  for number, signal in enumerate(signals, start=1):
    text = f"{signal.code}: {signal.message}\n{signal.text}"
    candidates.append(EvidenceItem(f"S{number}", "signal", signal.path, signal.line, signal.line, text))
  hunk_number = 0
  for file in files:
    for hunk in file.hunks:
      hunk_number += 1
      candidates.append(
        EvidenceItem(
          f"H{hunk_number}", "hunk", file.path, hunk.new_start, hunk.new_end, hunk.text(),
          tuple(sorted(line.new_line for line in hunk.added)),
        )
      )
  number = 0
  seen_functions: set[tuple[str, int]] = set()  # two hunks in one function: add it once
  for (path, _), spans in functions.items():
    for start, end, text in spans:
      if (path, start) in seen_functions:
        continue
      seen_functions.add((path, start))
      number += 1
      candidates.append(EvidenceItem(f"F{number}", "function", path, start, end, text))
  seen: set[int] = set()
  number = 0
  for rank in range(RETRIEVED_PER_HUNK):  # every hunk's best match before any second-best
    for chunks in related.values():
      if rank < len(chunks) and chunks[rank].chunk_id not in seen:
        chunk = chunks[rank]
        seen.add(chunk.chunk_id)
        number += 1
        candidates.append(EvidenceItem(f"R{number}", "related", chunk.path, chunk.start_line, chunk.end_line, chunk.content))

  for item in candidates:
    cost = estimate_tokens(item.text)
    if cost <= remaining:
      bundle.items.append(item)
      remaining -= cost
    else:
      bundle.dropped += 1
  return bundle


async def collect_evidence(
  db: Session, github: GitHubClient, embedder: Embedder, pull_request: PullRequest, budget: int = DEFAULT_TOKEN_BUDGET
) -> EvidenceBundle:
  """Build the bundle from the database, GitHub (file contents at the head) and the index."""
  repository = db.get(Repository, pull_request.repository_id)
  rows = db.scalars(
    select(PullRequestFile).where(PullRequestFile.pull_request_id == pull_request.id).order_by(PullRequestFile.path)
  ).all()
  files = [
    FileDiff(row.path, row.status, row.additions, row.deletions, tuple(parse_patch(row.patch)))
    for row in rows
    if skip_reason(row.path) is None
  ]
  blob_shas = {row.path: row.blob_sha for row in rows}

  # The whole function around each hunk, from the file as it is at the PR's head commit
  functions: dict[tuple[str, int], list[tuple[int, int, str]]] = {}
  for file in files:
    language = detect_language(file.path)
    if file.status == "removed" or not language or not blob_shas.get(file.path) or not file.hunks:
      continue
    content = await get_file_text(db, github, repository.full_name, blob_shas[file.path])
    if not content:
      continue
    chunks = [chunk for chunk in chunk_file(file.path, content, language) if chunk.kind != "window"]
    for index, hunk in enumerate(file.hunks):
      changed = {line.new_line for line in hunk.added}
      functions[(file.path, index)] = [
        (chunk.start_line, chunk.end_line, chunk.content)
        for chunk in chunks
        if any(chunk.start_line <= line <= chunk.end_line for line in changed)
      ]

  related: dict[tuple[str, int], list[RetrievedChunk]] = {}
  if db.scalar(select(exists().where(CodeChunk.repository_id == repository.id))):
    hunks = [(file.path, index, hunk) for file in files for index, hunk in enumerate(file.hunks)]
    for path, index, hunk in hunks[:MAX_RETRIEVAL_HUNKS]:
      found = retrieve(db, embedder, repository.id, f"{path}\n{hunk.text()}", k=RETRIEVED_PER_HUNK + 2)
      # The changed code itself (old version, same place) is not "related": skip it
      related[(path, index)] = [
        chunk for chunk in found
        if not (chunk.path == path and chunk.start_line <= hunk.new_end and chunk.end_line >= hunk.new_start)
      ][:RETRIEVED_PER_HUNK]

  return build_bundle(
    pull_request.title, pull_request.body or "", files, detect_signals(files), functions, related, budget
  )
