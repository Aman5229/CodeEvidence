"""Parse a unified diff (a GitHub `patch`) into hunks with old and new line numbers.

A hunk starts with a header like `@@ -10,4 +10,6 @@ def handler():`: 4 lines from line 10
of the old file became 6 lines from line 10 of the new file. Then each line starts with
' ' (unchanged), '-' (removed) or '+' (added).
"""

import re
from dataclasses import dataclass

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


@dataclass(frozen=True)
class DiffLine:
  kind: str  # added, removed, context
  old_line: int | None  # None for added lines
  new_line: int | None  # None for removed lines
  text: str


@dataclass(frozen=True)
class Hunk:
  old_start: int
  old_count: int
  new_start: int
  new_count: int
  section: str  # the text after the second @@, often the enclosing function
  lines: tuple[DiffLine, ...]

  @property
  def added(self) -> list[DiffLine]:
    return [line for line in self.lines if line.kind == "added"]

  @property
  def removed(self) -> list[DiffLine]:
    return [line for line in self.lines if line.kind == "removed"]

  @property
  def new_lines(self) -> set[int]:
    """Line numbers in the new file that this hunk shows (added or unchanged)."""
    return {line.new_line for line in self.lines if line.new_line is not None}

  @property
  def new_end(self) -> int:
    return self.new_start + max(self.new_count, 1) - 1

  def text(self) -> str:
    prefix = {"added": "+", "removed": "-", "context": " "}
    header = f"@@ -{self.old_start},{self.old_count} +{self.new_start},{self.new_count} @@ {self.section}"
    return "\n".join([header.rstrip(), *(prefix[line.kind] + line.text for line in self.lines)])


def parse_patch(patch: str | None) -> list[Hunk]:
  """Hunks of one file's patch. Text before the first header is ignored."""
  hunks: list[Hunk] = []
  if not patch:
    return hunks
  header = None
  lines: list[DiffLine] = []
  old_no = new_no = 0

  def close() -> None:
    if header is not None:
      hunks.append(Hunk(*header, tuple(lines)))

  for raw in patch.splitlines():
    match = HUNK_HEADER.match(raw)
    if match:
      close()
      old_start, old_count, new_start, new_count, section = match.groups()
      header = (
        int(old_start),
        int(old_count) if old_count is not None else 1,
        int(new_start),
        int(new_count) if new_count is not None else 1,
        section.strip(),
      )
      lines = []
      old_no, new_no = header[0], header[2]
    elif header is None or raw.startswith("\\"):
      continue  # before the first hunk, or "\ No newline at end of file"
    elif raw.startswith("+"):
      lines.append(DiffLine("added", None, new_no, raw[1:]))
      new_no += 1
    elif raw.startswith("-"):
      lines.append(DiffLine("removed", old_no, None, raw[1:]))
      old_no += 1
    else:
      lines.append(DiffLine("context", old_no, new_no, raw[1:]))
      old_no += 1
      new_no += 1
  close()
  return hunks
