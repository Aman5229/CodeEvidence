"""Impact (blast radius): the code a PR changes, and the other code that uses it.

1. Changed symbols, per file: the functions, methods and classes the PR adds, edits or
   deletes. Added lines are matched against the file as it is at the PR's head (parsed like
   the code index does); removed lines against the code index of the default branch.
2. Dependents: indexed code in other files that mentions one of those names as a whole word.

What it can and cannot see:
- Python and JavaScript are parsed, so their symbols are exact. For other languages only
  definitions written on added lines are found (def, class, function, const f = () =>).
- The index holds functions and classes of the default branch: uses at module level, and
  code that exists only in other branches, are not found.
- For a PR merged before the index was built, the index already holds the PR's own version of
  its files: what changed can then only be called "changed", not added or modified.
- A name can match an unrelated function with the same name. Very short and very common
  names (get, run, save, __init__...) are not searched, to keep that rare.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import CodeChunk, PullRequest, PullRequestFile, Repository
from app.integrations.github.client import GitHubClient
from app.modules.code.chunking import GRAMMARS, chunk_file
from app.modules.code.contents import get_file_text
from app.modules.code.diff import parse_patch
from app.modules.code.filters import detect_language, skip_reason
from app.modules.risk.features import is_test_file

MAX_FILES = 25  # code files read for their definitions
MAX_NAMES = 40  # names searched in the rest of the code
MAX_DEPENDENT_CHUNKS = 300
MAX_DEPENDENT_FILES = 40
MIN_NAME_LENGTH = 4
COMMON_NAMES = {
  "main", "init", "call", "handle", "handler", "test", "tests", "setup", "teardown", "close", "open", "read",
  "write", "start", "stop", "process", "execute", "build", "parse", "render", "index", "show", "list", "view",
  "self", "this", "value", "values", "data", "name", "items", "keys", "copy", "save", "load", "create",
  "update", "delete", "fetch", "send", "apply", "check", "clean", "reset", "clear", "next", "prev", "wrapper",
  "inner", "default", "config", "options", "props", "state", "error", "result", "response", "request",
}
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
DEFINITION = re.compile(
  r"^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(def|class|function\*?)\s+([A-Za-z_]\w*)"
  r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s+)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_]\w*\s*=>)"
)


@dataclass(frozen=True)
class ChangedSymbol:
  name: str  # as the index names it: Class.method for methods of large classes
  kind: str  # function, method, class
  change: str  # added, modified, removed; "changed" when the index cannot tell which


@dataclass
class DependentChunk:
  name: str | None
  kind: str
  start_line: int
  end_line: int
  uses: list[str]


@dataclass
class DependentFile:
  path: str
  is_test: bool
  uses: list[str]  # the changed names it mentions
  changed_files: list[str]  # the changed files that define them
  chunks: list[DependentChunk] = field(default_factory=list)


@dataclass
class ChangedFile:
  path: str
  status: str
  additions: int
  deletions: int
  symbols: list[ChangedSymbol]


@dataclass
class Impact:
  indexed: bool
  changed: list[ChangedFile]
  dependents: list[DependentFile]
  truncated: bool  # more dependents than shown, or files not read


def search_word(symbol_name: str) -> str | None:
  """The word to look for in other code, or None when it is too short or too common."""
  word = symbol_name.rsplit(".", 1)[-1]
  if not IDENTIFIER.fullmatch(word) or len(word) < MIN_NAME_LENGTH:
    return None
  if word.lower() in COMMON_NAMES or (word.startswith("__") and word.endswith("__")):
    return None
  return word


def defined_names(lines: list[str]) -> list[tuple[str, str]]:
  """(name, kind) of definitions written on these lines (any language)."""
  found = []
  for line in lines:
    match = DEFINITION.match(line)
    if match:
      keyword, name, variable = match.groups()
      if name:
        kind = "class" if keyword == "class" else ("method" if keyword == "def" and line[:1].isspace() else "function")
        found.append((name, kind))
      elif variable:
        found.append((variable, "function"))
  return found


def changed_symbols(
  file: PullRequestFile, head_text: str | None, base_chunks: list[CodeChunk] | None
) -> list[ChangedSymbol]:
  """The symbols one file's changes touch. `base_chunks` is the indexed (default branch)
  version of the file from before the PR, or None when there is none to compare with."""
  hunks = parse_patch(file.patch)
  added = {line.new_line for hunk in hunks for line in hunk.added}
  removed = {line.old_line for hunk in hunks for line in hunk.removed}
  base = [chunk for chunk in base_chunks or [] if chunk.name and chunk.kind != "window"]
  base_names = {chunk.name for chunk in base}
  symbols: dict[str, ChangedSymbol] = {}

  def change_of(name: str) -> str:
    if file.status == "added":
      return "added"  # the file did not exist before the PR
    if base_chunks is None:
      return "changed"
    return "modified" if name in base_names else "added"

  if file.status == "removed":
    return [ChangedSymbol(chunk.name, chunk.kind, "removed") for chunk in base]

  language = detect_language(file.path)
  head_names: set[str] | None = None
  if head_text is not None and language in GRAMMARS:
    head_chunks = [chunk for chunk in chunk_file(file.path, head_text, language) if chunk.name and chunk.kind != "window"]
    head_names = {chunk.name for chunk in head_chunks}
    for chunk in head_chunks:
      if any(chunk.start_line <= number <= chunk.end_line for number in added):
        symbols.setdefault(chunk.name, ChangedSymbol(chunk.name, chunk.kind, change_of(chunk.name)))
  else:
    added_text = [line.text for hunk in hunks for line in hunk.added]
    for name, kind in defined_names(added_text):
      symbols.setdefault(name, ChangedSymbol(name, kind, change_of(name)))

  for chunk in base:  # edits and deletions inside code that existed before
    if chunk.name not in symbols and any(chunk.start_line <= number <= chunk.end_line for number in removed):
      gone = head_names is not None and chunk.name not in head_names
      symbols[chunk.name] = ChangedSymbol(chunk.name, chunk.kind, "removed" if gone else "modified")
  return list(symbols.values())


async def compute_impact(db: Session, github: GitHubClient, pull_request: PullRequest) -> Impact:
  repository = db.get(Repository, pull_request.repository_id)
  indexed = bool(db.scalar(select(exists().where(CodeChunk.repository_id == repository.id))))
  files = db.scalars(
    select(PullRequestFile).where(PullRequestFile.pull_request_id == pull_request.id).order_by(PullRequestFile.path)
  ).all()
  code_files = [file for file in files if detect_language(file.path) and skip_reason(file.path) is None]
  truncated = len(code_files) > MAX_FILES
  code_files = code_files[:MAX_FILES]

  changed: list[ChangedFile] = []
  for file in code_files:
    head_text = None
    if file.status != "removed" and file.blob_sha and detect_language(file.path) in GRAMMARS:
      head_text = await get_file_text(db, github, repository.full_name, file.blob_sha)
    base_chunks = None
    if indexed:
      base_path = file.previous_path or file.path
      base_chunks = list(
        db.scalars(select(CodeChunk).where(CodeChunk.repository_id == repository.id, CodeChunk.path == base_path))
      )
      merged = pull_request.merged_at
      if merged is not None and any(chunk.created_at > merged for chunk in base_chunks):
        base_chunks = None  # indexed after the merge: the index holds this PR's version already
    changed.append(
      ChangedFile(file.path, file.status, file.additions, file.deletions, changed_symbols(file, head_text, base_chunks))
    )

  dependents: list[DependentFile] = []
  if indexed:
    dependents, more = find_dependents(db, repository.id, changed, {f.previous_path for f in files if f.previous_path})
    truncated = truncated or more
  return Impact(indexed, changed, dependents, truncated)


def find_dependents(
  db: Session, repository_id: int, changed: list[ChangedFile], old_paths: set[str]
) -> tuple[list[DependentFile], bool]:
  """Indexed code outside the changed files that mentions a changed name. Returns the
  dependents (most uses first) and whether the list was cut."""
  defined_in: dict[str, set[str]] = {}
  for file in changed:
    for symbol in file.symbols:
      word = search_word(symbol.name)
      if word:
        defined_in.setdefault(word, set()).add(file.path)
  words = sorted(defined_in)[:MAX_NAMES]
  if not words:
    return [], False
  skip = {file.path for file in changed} | old_paths
  rows = db.scalars(
    select(CodeChunk)
    .where(
      CodeChunk.repository_id == repository_id,
      CodeChunk.path.not_in(skip),
      CodeChunk.content.regexp_match(r"\m(" + "|".join(words) + r")\M"),  # Postgres: whole words
    )
    .order_by(CodeChunk.path, CodeChunk.start_line)
    .limit(MAX_DEPENDENT_CHUNKS + 1)
  ).all()
  cut = len(rows) > MAX_DEPENDENT_CHUNKS

  by_path: dict[str, DependentFile] = {}
  wanted = set(words)
  for chunk in rows[:MAX_DEPENDENT_CHUNKS]:
    tokens = IDENTIFIER.findall(chunk.content)
    own = (chunk.name or "").rsplit(".", 1)[-1]
    # A function with the same name as a changed one is a namesake, not a use
    uses = sorted(word for word in wanted.intersection(tokens) if not (word == own and tokens.count(word) == 1))
    if not uses:
      continue
    dependent = by_path.setdefault(chunk.path, DependentFile(chunk.path, is_test_file(chunk.path), [], []))
    dependent.chunks.append(DependentChunk(chunk.name, chunk.kind, chunk.start_line, chunk.end_line, uses))
  for dependent in by_path.values():
    used = sorted({word for chunk in dependent.chunks for word in chunk.uses})
    dependent.uses = used
    dependent.changed_files = sorted({path for word in used for path in defined_in[word]})
  ordered = sorted(by_path.values(), key=lambda d: (-len(d.uses), -len(d.chunks), d.path))
  return ordered[:MAX_DEPENDENT_FILES], cut or len(ordered) > MAX_DEPENDENT_FILES
