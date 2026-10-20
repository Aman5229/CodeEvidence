"""Deterministic signals: known risky patterns found by plain rules, with file and line.

For patterns that a regular expression can find, a rule is cheaper, faster and more
reliable than asking an LLM. Signals become evidence the LLM can cite, and they never
hallucinate. Only added lines are checked: the PR is responsible for what it adds.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.modules.code.diff import Hunk
from app.modules.code.filters import LOCK_FILES, detect_language
from app.modules.risk.features import is_doc_file, is_test_file

DEPENDENCY_FILES = {
  "requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "pipfile", "package.json",
  "gemfile", "go.mod", "cargo.toml", "pom.xml", "build.gradle", "composer.json",
} | LOCK_FILES
MISSING_TESTS_MIN_LINES = 50  # small changes without tests are normal


@dataclass(frozen=True)
class Pattern:
  code: str
  regex: re.Pattern
  message: str
  severity: str


PATTERNS = [
  Pattern("dynamic_code_execution", re.compile(r"\b(eval|exec)\s*\("), "Runs dynamically built code (eval/exec)", "high"),
  Pattern("shell_injection_risk", re.compile(r"shell\s*=\s*True"), "Starts a shell (shell=True): injection risk if input is not trusted", "high"),
  Pattern("unsafe_deserialization", re.compile(r"\bpickle\.loads?\(|\byaml\.load\((?![^)]*Loader)"), "Deserializes data in a way that can run code", "high"),
  Pattern("tls_verification_disabled", re.compile(r"verify\s*=\s*False|rejectUnauthorized\s*:\s*false"), "Turns off TLS certificate checks", "high"),
  Pattern("sql_built_from_strings", re.compile(r"\.execute\(\s*f[\"']|\.execute\([^)]*[\"']\s*(%|\+)\s*\w"), "Builds SQL from strings: injection risk", "high"),
  Pattern("hardcoded_secret", re.compile(r"(?i)\b(password|passwd|secret|api_key|apikey|token)\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']|AKIA[0-9A-Z]{16}"), "Looks like a secret written into the code", "high"),
  Pattern("bare_except", re.compile(r"^\s*except\s*:"), "Catches every exception, including ones that should stop the program", "medium"),
  Pattern("debugger_left_in", re.compile(r"\b(breakpoint\(\)|pdb\.set_trace\(\)|debugger;)"), "A debugger call left in", "medium"),
  Pattern("todo_added", re.compile(r"\b(TODO|FIXME|XXX|HACK)\b"), "Adds a TODO/FIXME: unfinished work", "low"),
]


@dataclass(frozen=True)
class FileDiff:
  path: str
  status: str  # added, modified, removed, renamed
  additions: int
  deletions: int
  hunks: tuple[Hunk, ...]


@dataclass(frozen=True)
class Signal:
  code: str
  message: str
  severity: str  # low, medium, high
  path: str | None  # None for signals about the whole PR
  line: int | None  # line in the new file
  text: str  # the matching line, or a short description


def detect_signals(files: list[FileDiff]) -> list[Signal]:
  signals: list[Signal] = []
  for file in files:
    if PurePosixPath(file.path.lower()).name in DEPENDENCY_FILES:
      signals.append(
        Signal("dependency_change", "Changes dependencies: check versions and licences", "medium", file.path, None, file.path)
      )
    if detect_language(file.path) is None:
      continue  # patterns are for code only
    for hunk in file.hunks:
      for line in hunk.added:
        for pattern in PATTERNS:
          if pattern.regex.search(line.text):
            signals.append(Signal(pattern.code, pattern.message, pattern.severity, file.path, line.new_line, line.text.strip()))

  code_files = [f for f in files if detect_language(f.path) and not is_test_file(f.path) and not is_doc_file(f.path)]
  code_lines = sum(f.additions + f.deletions for f in code_files)
  if code_lines >= MISSING_TESTS_MIN_LINES and not any(is_test_file(f.path) for f in files):
    signals.append(
      Signal(
        "missing_tests",
        f"Changes {code_lines} lines of code without changing any test",
        "medium",
        None,
        None,
        ", ".join(f.path for f in code_files[:5]),
      )
    )
  return signals
