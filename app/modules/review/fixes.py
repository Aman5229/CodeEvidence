"""Turning a finding into something a person or a coding agent can act on in one step."""


def agent_prompt(*, path: str, line: int, claim: str, quote: str, suggestion: str | None, replacement: str | None) -> str:
  """A self-contained instruction to paste into an AI coding agent (Claude Code, Cursor...)."""
  parts = [f"In `{path}` at line {line}: {claim}", f"The code is: `{quote.strip()}`"]
  if suggestion:
    parts.append(f"How to fix it: {suggestion}")
  if replacement:
    parts.append(f"Suggested new text for that line:\n{replacement}")
  parts.append("Make the smallest change that fixes this, keep the existing style, and add or update a test if the behaviour changes.")
  return "\n".join(parts)
