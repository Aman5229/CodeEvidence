"""Split code into words, so `getUserById` and `get_user_by_id` both match "user"."""

import re

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
CAMEL_PARTS = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def code_tokens(text: str) -> list[str]:
  """Lower-case words of every identifier, in order; the whole identifier is kept too."""
  tokens: list[str] = []
  for identifier in IDENTIFIER.findall(text):
    parts = [part.lower() for piece in identifier.split("_") for part in CAMEL_PARTS.findall(piece)]
    tokens.extend(part for part in parts if len(part) > 1)
    if len(parts) > 1:
      tokens.append(identifier.lower())
  return tokens
