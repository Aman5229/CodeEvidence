"""Static analysis tools as signals: output parsing, added lines only, masking, missing tools."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import app.modules.code.tools as tools
from app.modules.code.tools import RawIssue, parse_gitleaks, parse_ruff, parse_semgrep, run_tools


@pytest.fixture
def root(tmp_path) -> Path:
  return Path(os.path.realpath(tmp_path))


def test_ruff_output_is_read(root):
  output = json.dumps([{
    "code": "S602", "filename": str(root / "app/run.py"), "location": {"row": 3, "column": 5},
    "end_location": {"row": 3, "column": 40}, "message": "`subprocess` call with `shell=True` identified",
    "fix": None, "noqa_row": 3, "url": "https://docs.astral.sh/ruff/rules/",
  }])

  assert parse_ruff(output, root) == [
    RawIssue("app/run.py", 3, "S602", "`subprocess` call with `shell=True` identified", "medium")
  ]
  assert parse_ruff("", root) == []


def test_ruff_syntax_errors_and_undefined_names_are_high():
  assert tools.ruff_severity("F821") == "high"
  assert tools.ruff_severity("E999") == "high"
  assert tools.ruff_severity("B006") == "medium"


def test_semgrep_output_is_read(root):
  output = json.dumps({
    "results": [
      {"check_id": "private.tmp.rules.yaml-unsafe-load", "path": "app/conf.py", "start": {"line": 4},
       "end": {"line": 4}, "extra": {"message": "yaml.load can run code", "severity": "ERROR"}},
      {"check_id": "weak-hash", "path": str(root / "app/hash.py"), "start": {"line": 9},
       "end": {"line": 9}, "extra": {"message": "MD5 is weak", "severity": "WARNING"}},
    ],
    "errors": [],
  })

  assert parse_semgrep(output, root) == [
    RawIssue("app/conf.py", 4, "yaml-unsafe-load", "yaml.load can run code", "high"),
    RawIssue("app/hash.py", 9, "weak-hash", "MD5 is weak", "medium"),
  ]


def test_gitleaks_report_is_read(root):
  report = json.dumps([{
    "Description": "AWS Access Key", "StartLine": 2, "EndLine": 2, "Match": "key = AKIAABCDEFGHIJKLMNOP",
    "Secret": "AKIAABCDEFGHIJKLMNOP", "File": str(root / "config/settings.py"), "RuleID": "aws-access-token",
  }])

  assert parse_gitleaks(report, root) == [
    RawIssue("config/settings.py", 2, "aws-access-token", "Possible secret: AWS Access Key", "high", "AKIAABCDEFGHIJKLMNOP")
  ]
  assert parse_gitleaks("null", root) == []  # gitleaks writes null when it finds nothing


@pytest.fixture
def fake_tools(monkeypatch):
  """Every tool 'installed', with canned issues instead of real runs."""
  monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
  issues = {
    "ruff": [RawIssue("app/run.py", 2, "S602", "shell=True", "medium"), RawIssue("app/run.py", 1, "F401", "unused", "high")],
    "semgrep": [],
    "gitleaks": [RawIssue("app/run.py", 3, "generic-api-key", "Possible secret", "high", "sk_live_123456789")],
  }

  def runner(found: list[RawIssue]):
    return lambda *args: found

  monkeypatch.setattr(tools, "RUNNERS", {name: runner(found) for name, found in issues.items()})
  return issues


CONTENT = {"app/run.py": 'import os\nsubprocess.run(cmd, shell=True)\nAPI_KEY = "sk_live_123456789"\n'}


def test_only_issues_on_added_lines_become_signals_and_secrets_are_masked(fake_tools):
  signals, runs = run_tools(CONTENT, {"app/run.py": {2, 3}}, {"ruff": True, "semgrep": True, "gitleaks": True}, 10)

  assert [(s.code, s.path, s.line, s.severity) for s in signals] == [
    ("ruff:S602", "app/run.py", 2, "medium"),  # line 1 was not added by the PR: left out
    ("gitleaks:generic-api-key", "app/run.py", 3, "high"),
  ]
  assert signals[1].text == 'API_KEY = "****"'
  assert all("sk_live" not in s.text for s in signals)
  assert [(r.name, r.ran, r.findings) for r in runs] == [("ruff", True, 1), ("semgrep", True, 0), ("gitleaks", True, 1)]


def test_disabled_and_missing_tools(fake_tools, monkeypatch):
  monkeypatch.setattr(shutil, "which", lambda name: None if name == "gitleaks" else f"/usr/bin/{name}")

  _, runs = run_tools(CONTENT, {"app/run.py": {2}}, {"ruff": True, "semgrep": False, "gitleaks": True}, 10)

  assert [(r.name, r.ran, r.error) for r in runs] == [("ruff", True, None), ("gitleaks", False, "not installed")]


def test_a_tool_that_fails_is_reported_and_the_others_still_run(fake_tools, monkeypatch):
  def times_out(*args):
    raise subprocess.TimeoutExpired("ruff", 10)

  monkeypatch.setitem(tools.RUNNERS, "ruff", times_out)

  signals, runs = run_tools(CONTENT, {"app/run.py": {2, 3}}, {"ruff": True, "semgrep": True, "gitleaks": True}, 10)

  assert runs[0].name == "ruff" and not runs[0].ran and "timed out" in runs[0].error
  assert [s.code for s in signals] == ["gitleaks:generic-api-key"]


def test_file_names_cannot_escape_the_temporary_folder(root):
  written = tools._write_files(root, {"../evil.py": "x", "/etc/evil.py": "x", "app/ok.py": "x = 1\n"})

  assert written == ["app/ok.py"]
  assert not (root.parent / "evil.py").exists()


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")
def test_real_ruff_finds_shell_true_on_an_added_line():
  code = "import subprocess\n\n\ndef run(cmd):\n    return subprocess.run(cmd, shell=True)\n"

  signals, runs = run_tools({"app/run.py": code}, {"app/run.py": {5}}, {"ruff": True, "semgrep": False, "gitleaks": False}, 60)

  assert runs[0].ran and runs[0].error is None
  assert "ruff:S602" in [s.code for s in signals]
  assert all(s.line == 5 for s in signals)


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")
def test_real_ruff_leaves_security_smells_in_tests_alone():
  """Seen on a real flask PR: S105 on `app.secret_key = "secret"` in a test fixture became a
  high-severity "hardcoded secret" finding."""
  fixture = 'def test_login(app):\n    app.secret_key = "secret"\n    password = "hunter22"\n'
  files = {"tests/test_login.py": fixture, "app/login.py": fixture.replace("test_login", "login")}
  added = {path: {2, 3} for path in files}

  signals, _ = run_tools(files, added, {"ruff": True, "semgrep": False, "gitleaks": False}, 60)

  assert {s.path for s in signals} == {"app/login.py"}
