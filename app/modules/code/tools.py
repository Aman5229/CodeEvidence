"""Static analysis tools run on a PR's changed files: ruff, semgrep and gitleaks.

Their findings become signals: evidence the reviewer can cite, found by rules, never invented.
- Only problems on lines the PR added count: the PR is responsible for what it adds.
- A tool that is not installed is skipped and reported as such; the review goes on without it.
- The files are written to a temporary folder (the content at the PR's head commit). Paths
  are checked so a crafted file name cannot write outside that folder.
- Secrets found by gitleaks are masked before they are stored, shown or sent to a model.
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.modules.code.signals import Signal
from app.modules.risk.features import is_test_file

logger = logging.getLogger(__name__)

SEMGREP_RULES = Path(__file__).with_name("semgrep_rules.yml")
RUFF_RULES = "E9,F63,F7,F82,B,S"  # syntax errors, undefined names, likely bugs, security
RUFF_IGNORED = "S101"  # assert: normal in tests and scripts
SEMGREP_SUFFIXES = (".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
MAX_FILES = 200
TOOLS = ("ruff", "semgrep", "gitleaks")


@dataclass(frozen=True)
class ToolRun:
  name: str
  ran: bool
  findings: int = 0  # on added lines
  error: str | None = None
  duration_ms: int = 0


@dataclass(frozen=True)
class RawIssue:
  path: str
  line: int
  rule: str
  message: str
  severity: str  # low, medium, high
  secret: str | None = None  # gitleaks only: masked in the signal text


def run_tools(
  contents: dict[str, str], added: dict[str, set[int]], enabled: dict[str, bool], timeout: int
) -> tuple[list[Signal], list[ToolRun]]:
  """Run each enabled tool on the files; return signals on added lines and a report per tool."""
  signals: list[Signal] = []
  runs: list[ToolRun] = []
  files = dict(list(contents.items())[:MAX_FILES])
  with tempfile.TemporaryDirectory(prefix="codeevidence-tools-") as folder:
    root = Path(os.path.realpath(folder))  # tools report resolved paths (/private/var/... on macOS)
    written = _write_files(root, files)
    for name in TOOLS:
      if not enabled.get(name, True):
        continue
      binary = shutil.which(name)
      if binary is None:
        runs.append(ToolRun(name, ran=False, error="not installed"))
        continue
      started = time.perf_counter()
      try:
        issues = RUNNERS[name](binary, root, written, timeout)
      except (subprocess.SubprocessError, OSError, ValueError) as error:
        logger.warning("%s failed: %s", name, error)
        runs.append(ToolRun(name, ran=False, error=str(error)[:200], duration_ms=_ms(started)))
        continue
      kept = [issue for issue in issues if issue.line in added.get(issue.path, set())]
      signals.extend(_to_signal(name, issue, files) for issue in kept)
      runs.append(ToolRun(name, ran=True, findings=len(kept), duration_ms=_ms(started)))
  return signals, runs


def _write_files(root: Path, files: dict[str, str]) -> list[str]:
  written = []
  for path, text in files.items():
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts:
      continue  # never write outside the temporary folder
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    written.append(str(relative))
  return written


def _relative(root: Path, reported: str) -> str:
  path = Path(reported)
  if path.is_absolute():
    return Path(os.path.realpath(path)).relative_to(root).as_posix()
  return PurePosixPath(reported).as_posix()


def _ms(started: float) -> int:
  return round((time.perf_counter() - started) * 1000)


# ---------- ruff ----------

def run_ruff(binary: str, root: Path, paths: list[str], timeout: int) -> list[RawIssue]:
  targets = [path for path in paths if path.endswith(".py")]
  if not targets:
    return []
  output = subprocess.run(
    [binary, "check", "--isolated", "--no-cache", "--exit-zero", "--output-format", "json",
     "--select", RUFF_RULES, "--ignore", RUFF_IGNORED, "--target-version", "py312", *targets],
    cwd=root, capture_output=True, text=True, timeout=timeout, check=False,
  )
  # Security smells (S, from bandit) are noise in tests: fixtures use dummy passwords and keys.
  # Real secrets in tests are still found by gitleaks.
  return [issue for issue in parse_ruff(output.stdout, root) if not (issue.rule.startswith("S") and is_test_file(issue.path))]


def parse_ruff(output: str, root: Path) -> list[RawIssue]:
  return [
    RawIssue(
      path=_relative(root, item["filename"]),
      line=item["location"]["row"],
      rule=item["code"] or "ruff",
      message=item["message"],
      severity=ruff_severity(item["code"] or ""),
    )
    for item in json.loads(output or "[]")
  ]


def ruff_severity(code: str) -> str:
  if code.startswith(("E9", "F")):  # syntax errors, undefined names: it will break
    return "high"
  return "medium"  # B (likely bugs), S (security smells)


# ---------- semgrep ----------

def run_semgrep(binary: str, root: Path, paths: list[str], timeout: int) -> list[RawIssue]:
  targets = [path for path in paths if path.endswith(SEMGREP_SUFFIXES)]
  if not targets:
    return []
  output = subprocess.run(
    [binary, "scan", "--config", str(SEMGREP_RULES), "--json", "--quiet", "--metrics=off",
     "--disable-version-check", *targets],
    cwd=root, capture_output=True, text=True, timeout=timeout, check=False,
  )
  return parse_semgrep(output.stdout, root)


SEMGREP_SEVERITY = {"ERROR": "high", "CRITICAL": "high", "HIGH": "high", "WARNING": "medium", "MEDIUM": "medium"}


def parse_semgrep(output: str, root: Path) -> list[RawIssue]:
  data = json.loads(output or "{}")
  return [
    RawIssue(
      path=_relative(root, result["path"]),
      line=result["start"]["line"],
      rule=result["check_id"].rsplit(".", 1)[-1],  # local rules are prefixed with the file path
      message=result["extra"]["message"],
      severity=SEMGREP_SEVERITY.get(str(result["extra"].get("severity", "")).upper(), "low"),
    )
    for result in data.get("results", [])
  ]


# ---------- gitleaks ----------

def run_gitleaks(binary: str, root: Path, paths: list[str], timeout: int) -> list[RawIssue]:
  if not paths:
    return []
  report = root.parent / f"{root.name}-gitleaks.json"
  try:
    subprocess.run(
      [binary, "detect", "--no-git", "--no-banner", "--source", str(root), "--report-format", "json",
       "--report-path", str(report), "--exit-code", "0", "--log-level", "error"],
      capture_output=True, text=True, timeout=timeout, check=False,
    )
    return parse_gitleaks(report.read_text() if report.exists() else "[]", root)
  finally:
    report.unlink(missing_ok=True)


def parse_gitleaks(output: str, root: Path) -> list[RawIssue]:
  return [
    RawIssue(
      path=_relative(root, item["File"]),
      line=item["StartLine"],
      rule=item.get("RuleID") or "secret",
      message=f"Possible secret: {item.get('Description') or item.get('RuleID') or 'credential'}",
      severity="high",
      secret=item.get("Secret") or None,
    )
    for item in json.loads(output or "[]") or []
  ]


RUNNERS = {"ruff": run_ruff, "semgrep": run_semgrep, "gitleaks": run_gitleaks}


def _to_signal(tool: str, issue: RawIssue, files: dict[str, str]) -> Signal:
  lines = files.get(issue.path, "").splitlines()
  text = lines[issue.line - 1].strip() if 0 < issue.line <= len(lines) else ""
  if issue.secret:
    text = text.replace(issue.secret, "****")  # the secret itself never leaves this function
  return Signal(f"{tool}:{issue.rule}", issue.message, issue.severity, issue.path, issue.line, text)
