"""Turn a pull request into numbers that a risk score (and later an ML model) can use.

Only information available when the PR is opened is used. Merge or close times would leak
the outcome a model may later have to predict.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import PurePosixPath

DOC_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
DOC_FOLDERS = {"doc", "docs"}
TEST_FOLDERS = {"test", "tests", "spec", "specs", "__tests__"}


@dataclass(frozen=True)
class ChangedFile:
  path: str
  additions: int
  deletions: int


@dataclass(frozen=True)
class PullRequestFeatures:
  files_changed: int
  lines_changed: int
  log_lines_changed: float
  test_file_ratio: float  # share of changed files that are tests, 0 to 1
  docs_only: bool
  is_bot: bool
  size_percentile: float  # share of the repository's PRs this size or smaller, 0 to 1


def is_test_file(path: str) -> bool:
  file = PurePosixPath(path.lower())
  if any(folder in TEST_FOLDERS for folder in file.parts[:-1]):
    return True
  return file.name.startswith("test_") or file.stem.endswith(("_test", "_spec", ".test", ".spec"))


def is_doc_file(path: str) -> bool:
  file = PurePosixPath(path.lower())
  return file.suffix in DOC_EXTENSIONS or file.parts[0] in DOC_FOLDERS


def size_percentile(lines_changed: int, repo_line_counts: list[int]) -> float:
  """Share of the repository's PRs (line counts, sorted ascending) at or below this size."""
  if not repo_line_counts:
    return 0.5  # no history yet: treat it as a typical PR
  return bisect_right(repo_line_counts, lines_changed) / len(repo_line_counts)


def extract_features(
  files: list[ChangedFile], author_login: str | None, repo_line_counts: list[int]
) -> PullRequestFeatures:
  lines_changed = sum(file.additions + file.deletions for file in files)
  test_files = sum(is_test_file(file.path) for file in files)
  return PullRequestFeatures(
    files_changed=len(files),
    lines_changed=lines_changed,
    log_lines_changed=math.log1p(lines_changed),
    test_file_ratio=test_files / len(files) if files else 0.0,
    docs_only=bool(files) and all(is_doc_file(file.path) for file in files),
    is_bot=bool(author_login) and author_login.endswith("[bot]"),
    size_percentile=size_percentile(lines_changed, repo_line_counts),
  )
