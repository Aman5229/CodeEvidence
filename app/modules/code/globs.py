"""Path patterns, the way .gitignore reads them.

- `*` matches within one folder name, `**` across folders: `src/**/*.py`, `docs/**`.
- A pattern without a slash matches a file name in any folder: `*.md`, `package.json`.
- A plain folder name (`docs` or `docs/`) covers everything inside it.
"""

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import PurePosixPath


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern:
  regex, index = "", 0
  while index < len(pattern):
    if pattern.startswith("**/", index):
      regex, index = regex + "(?:.*/)?", index + 3
    elif pattern.startswith("**", index):
      regex, index = regex + ".*", index + 2
    elif pattern[index] == "*":
      regex, index = regex + "[^/]*", index + 1
    elif pattern[index] == "?":
      regex, index = regex + "[^/]", index + 1
    else:
      regex, index = regex + re.escape(pattern[index]), index + 1
  return re.compile(regex + r"\Z")


def path_matches(path: str, pattern: str) -> bool:
  path = path.lstrip("/")
  pattern = pattern.strip().lstrip("/")
  if not pattern:
    return False
  folder = pattern.rstrip("/")
  if not any(char in folder for char in "*?") and (path == folder or path.startswith(folder + "/")):
    return True
  if "/" not in folder:  # a bare name or *.ext: any folder
    return bool(_compile(folder).match(PurePosixPath(path).name))
  return bool(_compile(pattern).match(path))


def matches_any(path: str, patterns: Iterable[str]) -> bool:
  return any(path_matches(path, pattern) for pattern in patterns)
