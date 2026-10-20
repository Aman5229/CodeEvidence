"""Repository settings (.codeevidence.yaml) and the path patterns they use."""

import pytest

from app.modules.code.globs import matches_any, path_matches
from app.modules.review.repo_config import RepoConfig, instructions_for, parse_config


# ---------- path patterns ----------

@pytest.mark.parametrize(
  ("path", "pattern", "expected"),
  [
    ("docs/guide/setup.md", "docs/**", True),
    ("docs", "docs/**", False),  # the folder itself is not a file inside it
    ("docs/guide/setup.md", "docs", True),  # a plain folder name covers what is inside
    ("docs/guide/setup.md", "docs/", True),
    ("mydocs/setup.md", "docs", False),
    ("README.md", "*.md", True),  # no slash: the file name, in any folder
    ("app/notes/todo.md", "*.md", True),
    ("src/a.py", "src/*.py", True),
    ("src/sub/a.py", "src/*.py", False),  # * stays within one folder
    ("src/sub/a.py", "src/**/*.py", True),
    ("src/a.py", "src/**/*.py", True),  # **/ also matches no folder at all
    ("web/api.generated.ts", "**/*.generated.ts", True),
    ("api.generated.ts", "**/*.generated.ts", True),
    ("package.json", "package.json", True),
    ("web/package.json", "package.json", True),
    ("a/b.py", "/a/b.py", True),  # a leading slash means the repository root
    ("a/b.py", "", False),
  ],
)
def test_path_patterns_work_like_gitignore(path, pattern, expected):
  assert path_matches(path, pattern) is expected


def test_matches_any():
  assert matches_any("docs/a.md", ["src/**", "docs/**"])
  assert not matches_any("app/a.py", ["src/**", "docs/**"])
  assert not matches_any("app/a.py", [])


# ---------- parsing the settings file ----------

def test_no_file_or_an_empty_one_means_the_defaults():
  for raw in (None, "", "   \n", "# only a comment\n"):
    config, error = parse_config(raw)
    assert (config, error) == (RepoConfig(), None)
  defaults = RepoConfig()
  assert defaults.profile == "chill" and defaults.merge_check.block_on == "high"
  assert defaults.tools.ruff and defaults.tools.semgrep and defaults.tools.gitleaks and defaults.guidelines


def test_a_full_settings_file_is_read():
  config, error = parse_config(
    """
profile: assertive
exclude:
  - "docs/**"
instructions:
  - path: "src/api/**"
    text: "Every endpoint must check the API key."
guidelines: false
tools:
  semgrep: false
merge_check:
  block_on: medium
"""
  )

  assert error is None
  assert config.profile == "assertive" and config.exclude == ["docs/**"] and not config.guidelines
  assert [(i.path, i.text) for i in config.instructions] == [("src/api/**", "Every endpoint must check the API key.")]
  assert (config.tools.ruff, config.tools.semgrep, config.tools.gitleaks) == (True, False, True)
  assert config.merge_check.block_on == "medium"


@pytest.mark.parametrize(
  ("raw", "message"),
  [
    ("profile: [unclosed", "Not valid YAML"),
    ("- just\n- a list\n", "must be a mapping"),
    ("profil: chill\n", "profil: Extra inputs are not permitted"),  # a typo is reported, not ignored
    ("profile: loud\n", "profile: Input should be 'chill' or 'assertive'"),
    ("merge_check:\n  block_on: low\n", "merge_check.block_on"),
    ("instructions:\n  - path: src\n", "instructions.0.text: Field required"),
  ],
)
def test_a_broken_file_gives_the_defaults_and_says_why(raw, message):
  config, error = parse_config(raw)

  assert config == RepoConfig()
  assert message in error


def test_instructions_apply_only_to_matching_files():
  config, _ = parse_config(
    'instructions:\n  - path: "src/api/**"\n    text: "Check the API key."\n'
    '  - path: "*.sql"\n    text: "Migrations must be reversible."\n'
  )

  assert instructions_for(["src/api/users.py", "README.md"], config) == [("src/api/**", "Check the API key.")]
  assert instructions_for(["db/001.sql"], config) == [("*.sql", "Migrations must be reversible.")]
  assert instructions_for(["app/main.py"], config) == []


# ---------- guideline files ----------

class GuidelineGitHub:
  def __init__(self, files: dict[str, bytes]) -> None:
    self.files, self.asked = files, []

  async def get_file(self, repo_full_name: str, path: str, ref: str):
    self.asked.append((path, ref))
    return {"sha": "s", "content": self.files[path]} if path in self.files else None


def load(files: dict[str, bytes]):
  import asyncio
  from types import SimpleNamespace

  from app.modules.review.repo_config import load_repo_config

  github = GuidelineGitHub(files)
  repository = SimpleNamespace(full_name="octo/demo", default_branch="main")
  return asyncio.run(load_repo_config(github, repository)), github


def test_guidelines_are_read_from_the_default_branch_including_dot_github():
  loaded, github = load({".github/CONTRIBUTING.md": b"Run the tests.", "AGENTS.md": b"Use type hints.\n"})

  assert loaded.guidelines == [("AGENTS.md", "Use type hints."), (".github/CONTRIBUTING.md", "Run the tests.")]
  assert {ref for _, ref in github.asked} == {"main"}
  assert loaded.source == "default"


def test_guidelines_never_crowd_out_the_code():
  from app.modules.review.repo_config import MAX_GUIDELINE_CHARS, MAX_GUIDELINES_CHARS

  loaded, _ = load({name: b"x" * 5000 for name in ("CLAUDE.md", "AGENTS.md", ".cursorrules", "CONTRIBUTING.md")})

  assert [len(text) for _, text in loaded.guidelines] == [MAX_GUIDELINE_CHARS] * 3  # the total is full after three
  assert sum(len(text) for _, text in loaded.guidelines) == MAX_GUIDELINES_CHARS


def test_guidelines_can_be_turned_off():
  loaded, github = load({".codeevidence.yaml": b"guidelines: false\n", "CLAUDE.md": b"Rules."})

  assert loaded.guidelines == [] and [path for path, _ in github.asked] == [".codeevidence.yaml"]
