"""The evidence bundle: everything the reviewer may look at for one PR, trimmed to a budget.

Each item has an id the LLM must cite. The verifier later checks that cited ids exist, so a
finding can only stand on evidence that is really there.
- H: a diff hunk                       - F: the whole function around a hunk
- R: related code found by retrieval   - S: a signal from a rule or a static analysis tool
- L: a learning (a team rule from earlier reviews)
- P: an instruction for matching paths, from the repository's settings
- G: the repository's own guidelines (CLAUDE.md, CONTRIBUTING.md...)
- C: evidence carried over from an earlier review (incremental reviews)

When everything does not fit the token budget, items are kept in order of importance:
signals, learnings and instructions (short and decisive), hunks (the change itself),
guidelines, enclosing functions, then related code (best match of each hunk first).
"""

from dataclasses import asdict, dataclass, field

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import CodeChunk, PullRequest, PullRequestFile, Repository
from app.integrations.github.client import GitHubClient
from app.modules.code.chunking import chunk_file
from app.modules.code.contents import get_file_text
from app.modules.code.diff import parse_patch
from app.modules.code.embeddings import Embedder
from app.modules.code.filters import detect_language, skip_reason
from app.modules.code.globs import matches_any
from app.modules.code.retrieval import RetrievedChunk, retrieve
from app.modules.code.signals import FileDiff, Signal, detect_signals
from app.modules.code.tools import ToolRun, run_tools

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
  kind: str  # hunk, function, related, signal, learning, instruction, guideline
  path: str | None  # a file, or a path pattern for learnings and instructions
  start_line: int | None
  end_line: int | None
  text: str
  new_lines: tuple[int, ...] = ()  # hunks only: the new-file lines a comment may point at
  source_id: int | None = None  # learnings: the learning's id


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
    """Rebuild a stored bundle (a stored review, or a recorded evaluation case)."""
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
  *,
  learnings: list[tuple[int, str, str | None]] = (),
  instructions: list[tuple[str, str]] = (),
  guidelines: list[tuple[str, str]] = (),
) -> EvidenceBundle:
  """`functions` and `related` are keyed by (path, hunk index); functions are (start, end, text).
  Learnings are (id, text, path pattern), instructions (path pattern, text), guidelines
  (file name, text)."""
  description = description[: MAX_DESCRIPTION_TOKENS * 4]
  bundle = EvidenceBundle(title=title, description=description, budget=budget)
  remaining = budget - estimate_tokens(title) - estimate_tokens(description)

  candidates: list[EvidenceItem] = []
  for number, signal in enumerate(signals, start=1):
    text = f"{signal.code}: {signal.message}\n{signal.text}"
    candidates.append(EvidenceItem(f"S{number}", "signal", signal.path, signal.line, signal.line, text))
  for number, (learning_id, text, pattern) in enumerate(learnings, start=1):
    candidates.append(EvidenceItem(f"L{number}", "learning", pattern, None, None, text, source_id=learning_id))
  for number, (pattern, text) in enumerate(instructions, start=1):
    candidates.append(EvidenceItem(f"P{number}", "instruction", pattern, None, None, text))
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
  for number, (name, text) in enumerate(guidelines, start=1):
    candidates.append(EvidenceItem(f"G{number}", "guideline", name, None, None, text))
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


@dataclass
class EvidenceOptions:
  budget: int = DEFAULT_TOKEN_BUDGET
  only_paths: set[str] | None = None  # incremental review: only these files
  exclude: list[str] = field(default_factory=list)  # repository settings: never these files
  learnings: list[tuple[int, str, str | None]] = field(default_factory=list)
  instructions: list[tuple[str, str]] = field(default_factory=list)
  guidelines: list[tuple[str, str]] = field(default_factory=list)
  tools: dict[str, bool] | None = None  # which static analysis tools to run; None: none


@dataclass
class CollectedEvidence:
  bundle: EvidenceBundle  # what the reviewer sees
  summary_bundle: EvidenceBundle  # every hunk of the PR, for the summary and the diagram
  tool_runs: list[ToolRun] = field(default_factory=list)
  reviewed_paths: list[str] = field(default_factory=list)


def reviewable_files(db: Session, pull_request: PullRequest, exclude: list[str]) -> tuple[list[FileDiff], dict[str, str]]:
  """The PR's changed files worth reviewing, parsed, and their blob SHAs."""
  rows = db.scalars(
    select(PullRequestFile).where(PullRequestFile.pull_request_id == pull_request.id).order_by(PullRequestFile.path)
  ).all()
  files = [
    FileDiff(row.path, row.status, row.additions, row.deletions, tuple(parse_patch(row.patch)))
    for row in rows
    if skip_reason(row.path) is None and not matches_any(row.path, exclude)
  ]
  return files, {row.path: row.blob_sha for row in rows if row.blob_sha}


async def collect_evidence(
  db: Session,
  github: GitHubClient,
  embedder: Embedder,
  pull_request: PullRequest,
  options: EvidenceOptions | None = None,
) -> CollectedEvidence:
  """Build the bundle from the database, GitHub (file contents at the head), the code index
  and, when enabled, static analysis tools."""
  options = options or EvidenceOptions()
  repository = db.get(Repository, pull_request.repository_id)
  all_files, blob_shas = reviewable_files(db, pull_request, options.exclude)
  files = [file for file in all_files if options.only_paths is None or file.path in options.only_paths]
  paths = {file.path for file in files}

  # File contents at the PR's head: for enclosing functions and for static analysis
  contents: dict[str, str] = {}
  for file in files:
    if file.status == "removed" or not blob_shas.get(file.path) or not file.hunks:
      continue
    if options.tools is None and not detect_language(file.path):
      continue  # without tools, only code files are read (for their functions)
    text = await get_file_text(db, github, repository.full_name, blob_shas[file.path])
    if text:
      contents[file.path] = text

  functions: dict[tuple[str, int], list[tuple[int, int, str]]] = {}
  for file in files:
    language = detect_language(file.path)
    if file.path not in contents or not language:
      continue
    chunks = [chunk for chunk in chunk_file(file.path, contents[file.path], language) if chunk.kind != "window"]
    for index, hunk in enumerate(file.hunks):
      changed = {line.new_line for line in hunk.added}
      functions[(file.path, index)] = [
        (chunk.start_line, chunk.end_line, chunk.content)
        for chunk in chunks
        if any(chunk.start_line <= line <= chunk.end_line for line in changed)
      ]

  # Rules run on the whole PR (missing tests is about the whole PR), then keep what concerns
  # the files under review
  signals = [signal for signal in detect_signals(all_files) if signal.path is None or signal.path in paths]
  tool_runs: list[ToolRun] = []
  if options.tools is not None:
    added = {file.path: {line.new_line for hunk in file.hunks for line in hunk.added} for file in files}
    tool_signals, tool_runs = run_tools(contents, added, options.tools, settings.tool_timeout_seconds)
    signals.extend(tool_signals)

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

  bundle = build_bundle(
    pull_request.title, pull_request.body or "", files, signals, functions, related, options.budget,
    learnings=options.learnings, instructions=options.instructions, guidelines=options.guidelines,
  )
  summary_bundle = bundle
  if options.only_paths is not None:  # the summary and diagram describe the whole PR
    summary_bundle = build_bundle(pull_request.title, pull_request.body or "", all_files, [], {}, {}, options.budget)
  return CollectedEvidence(bundle, summary_bundle, tool_runs, sorted(paths))
