"""Per-repository review settings from `.codeevidence.yaml`, plus the repository's own
guideline files (CLAUDE.md, AGENTS.md, .cursorrules, .github/copilot-instructions.md and
CONTRIBUTING.md at the root or in .github/).

Both are read from the default branch, so a PR cannot change the rules it is reviewed by.
A missing file means the defaults; a broken one means the defaults plus a visible error:
settings never block a review.

Example `.codeevidence.yaml`:

    profile: chill            # chill (default): fewer comments, no low-severity nits
                              # assertive: more comments, low severity included
    exclude:                  # never reviewed
      - "docs/**"
      - "**/*.generated.ts"
    instructions:             # extra rules for matching files
      - path: "src/api/**"
        text: "Every endpoint must check the API key and validate its input."
    guidelines: true          # read CLAUDE.md, AGENTS.md, .cursorrules, CONTRIBUTING.md...
    tools:                    # static analysis on the changed files
      ruff: true
      semgrep: true
      gitleaks: true
    merge_check:
      block_on: high          # commit status fails on findings this severe: high, medium, never
"""

import asyncio
from dataclasses import dataclass, field
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.db.models import Repository
from app.integrations.github.client import GitHubClient
from app.modules.code.globs import path_matches

CONFIG_PATH = ".codeevidence.yaml"
# Instructions written for AI agents first, then the human contributing guide
GUIDELINE_FILES = (
  "CLAUDE.md", "AGENTS.md", ".cursorrules", ".github/copilot-instructions.md", "CONTRIBUTING.md",
  ".github/CONTRIBUTING.md",
)
MAX_GUIDELINE_CHARS = 1500  # each file, and all of them together at most:
MAX_GUIDELINES_CHARS = 4500  # guidelines must never crowd out the code under review


class _Strict(BaseModel):
  model_config = ConfigDict(extra="forbid")  # a misspelled key is reported, not silently ignored


class PathInstruction(_Strict):
  path: str = Field(min_length=1, max_length=255)
  text: str = Field(min_length=1, max_length=500)


class ToolsConfig(_Strict):
  ruff: bool = True
  semgrep: bool = True
  gitleaks: bool = True


class MergeCheck(_Strict):
  block_on: Literal["high", "medium", "never"] = "high"


class RepoConfig(_Strict):
  profile: Literal["chill", "assertive"] = "chill"
  exclude: list[str] = Field(default_factory=list, max_length=100)
  instructions: list[PathInstruction] = Field(default_factory=list, max_length=50)
  guidelines: bool = True
  tools: ToolsConfig = Field(default_factory=ToolsConfig)
  merge_check: MergeCheck = Field(default_factory=MergeCheck)


@dataclass
class LoadedConfig:
  config: RepoConfig
  source: str  # "file" or "default"
  error: str | None = None
  guidelines: list[tuple[str, str]] = field(default_factory=list)  # (file name, text)

  def summary(self) -> dict:
    """What a review stores about the settings it applied."""
    return {
      **self.config.model_dump(),
      "source": self.source,
      "error": self.error,
      "guideline_files": [name for name, _ in self.guidelines],
    }


def parse_config(raw: str | None) -> tuple[RepoConfig, str | None]:
  """The settings from the file's text, or the defaults and the reason the text was refused."""
  if raw is None or not raw.strip():
    return RepoConfig(), None
  try:
    data = yaml.safe_load(raw)
  except yaml.YAMLError as error:
    return RepoConfig(), f"Not valid YAML: {str(error).splitlines()[0]}"
  if data is None:
    return RepoConfig(), None
  if not isinstance(data, dict):
    return RepoConfig(), "The file must be a mapping of settings, like `profile: chill`"
  try:
    return RepoConfig.model_validate(data), None
  except ValidationError as error:
    problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()[:5])
    return RepoConfig(), f"Invalid settings ({problems}); the defaults were used"


async def load_repo_config(github: GitHubClient, repository: Repository) -> LoadedConfig:
  """Read the settings and guideline files from the repository's default branch."""
  file = await github.get_file(repository.full_name, CONFIG_PATH, repository.default_branch)
  raw = file["content"].decode("utf-8", errors="replace") if file else None
  config, error = parse_config(raw)
  loaded = LoadedConfig(config=config, source="file" if file else "default", error=error)
  if config.guidelines:
    found = await asyncio.gather(
      *(github.get_file(repository.full_name, name, repository.default_branch) for name in GUIDELINE_FILES)
    )
    room = MAX_GUIDELINES_CHARS
    for name, guideline in zip(GUIDELINE_FILES, found, strict=True):
      text = guideline["content"].decode("utf-8", errors="replace").strip() if guideline else ""
      if text and room > 0:
        kept = text[: min(MAX_GUIDELINE_CHARS, room)]
        loaded.guidelines.append((name, kept))
        room -= len(kept)
  return loaded


def instructions_for(paths: list[str], config: RepoConfig) -> list[tuple[str, str]]:
  """(path pattern, text) of every instruction that matches at least one changed file."""
  return [
    (instruction.path, instruction.text)
    for instruction in config.instructions
    if any(path_matches(path, instruction.path) for path in paths)
  ]
