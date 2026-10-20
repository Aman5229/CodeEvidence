"""Cut a source file into chunks along its structure: one per function, method or class.

A chunk that follows the code's structure is a complete thought (a whole function), so a
search hit makes sense on its own. Cutting every N characters would split functions in half.
tree-sitter parses the file into a syntax tree; we walk its top-level definitions.

Python and JavaScript are parsed. Other languages, very long definitions and files without
definitions fall back to overlapping windows of lines.
"""

from dataclasses import dataclass
from functools import cache

import tree_sitter_javascript
import tree_sitter_python
from tree_sitter import Language, Node, Parser

MAX_CHUNK_LINES = 120  # a longer definition is split into windows
WINDOW_LINES = 60
WINDOW_OVERLAP = 10

GRAMMARS = {"python": tree_sitter_python.language, "javascript": tree_sitter_javascript.language}
FUNCTIONS = {"function_definition", "function_declaration", "generator_function_declaration", "method_definition"}
CLASSES = {"class_definition", "class_declaration"}
VARIABLES = {"lexical_declaration", "variable_declaration"}
FUNCTION_VALUES = {"arrow_function", "function_expression", "function"}


@dataclass(frozen=True)
class Chunk:
  path: str
  language: str
  kind: str  # function, method, class, window
  name: str | None
  start_line: int  # 1-based, inclusive
  end_line: int
  content: str


@cache
def _parser(language: str) -> Parser:
  return Parser(Language(GRAMMARS[language]()))


def chunk_file(path: str, content: str, language: str) -> list[Chunk]:
  lines = content.splitlines()
  if not lines:
    return []
  chunks: list[Chunk] = []
  if language in GRAMMARS:
    root = _parser(language).parse(content.encode("utf-8")).root_node
    chunks = _chunk_definitions(root, path, language, lines, prefix="")
  return chunks or _windows(path, language, lines, 1, len(lines), kind="window", name=None)


def _chunk_definitions(node: Node, path: str, language: str, lines: list[str], prefix: str) -> list[Chunk]:
  chunks: list[Chunk] = []
  for span, target, name in _definitions(node):
    start, end = span.start_point[0] + 1, span.end_point[0] + 1
    if target.type in CLASSES:
      if end - start + 1 <= MAX_CHUNK_LINES:
        chunks.append(_chunk(path, language, lines, "class", prefix + name, start, end))
        continue
      body = target.child_by_field_name("body")
      methods = _chunk_definitions(body, path, language, lines, f"{prefix}{name}.") if body else []
      chunks.extend(methods or _windows(path, language, lines, start, end, "class", prefix + name))
    else:
      kind = "method" if prefix else "function"
      if end - start + 1 <= MAX_CHUNK_LINES:
        chunks.append(_chunk(path, language, lines, kind, prefix + name, start, end))
      else:
        chunks.extend(_windows(path, language, lines, start, end, kind, prefix + name))
  return chunks


def _definitions(node: Node):
  """(span, definition, name) for each function or class directly inside `node`.

  The span includes decorators and `export`, so the chunk shows them too.
  """
  for child in node.named_children:
    target = child
    if child.type in ("decorated_definition", "export_statement"):
      target = child.child_by_field_name("definition") or child.child_by_field_name("declaration")
      if target is None:
        continue
    if target.type in FUNCTIONS or target.type in CLASSES:
      name = target.child_by_field_name("name")
      if name is not None:
        yield child, target, name.text.decode()
    elif target.type in VARIABLES:  # const handler = () => { ... }
      for declarator in target.named_children:
        name, value = declarator.child_by_field_name("name"), declarator.child_by_field_name("value")
        if name is not None and value is not None and value.type in FUNCTION_VALUES:
          yield child, value, name.text.decode()


def _chunk(path, language, lines, kind, name, start, end) -> Chunk:
  return Chunk(path, language, kind, name, start, end, "\n".join(lines[start - 1 : end]))


def _windows(path, language, lines, start, end, kind, name) -> list[Chunk]:
  chunks = []
  step = WINDOW_LINES - WINDOW_OVERLAP
  for window_start in range(start, end + 1, step):
    window_end = min(end, window_start + WINDOW_LINES - 1)
    chunks.append(_chunk(path, language, lines, kind, name, window_start, window_end))
    if window_end == end:
      break
  return chunks
