"""A Mermaid sequence diagram of the flow a PR changes, for the walkthrough.

A diagram is only shown when it passes two checks:
- Syntax: every line must match the small part of Mermaid we allow. No HTML, no links, and no
  `%%` anywhere (Mermaid's comments and `%%{init}` configuration): a diagram can never smuggle
  markup or settings into the page.
- Grounding: at least half of the named participants must come from the code evidence (generic
  actors such as User or Database excepted), so the model cannot draw classes the PR does not
  have. A participant counts when its name, or one of the words in it, is in the evidence:
  models name things FlaskApp or TestClient rather than copying identifiers exactly.
"""

import re

from app.modules.code.evidence import EvidenceBundle
from app.modules.code.tokens import code_tokens
from app.modules.review.llm import CostMeter
from app.modules.review.prompts import data_tag, load_prompt, render_bundle

DIAGRAM_PROMPT = "diagram_v1"
MAX_OUTPUT_TOKENS = 700
MAX_LINES = 45
GENERIC_PARTICIPANTS = {
  "user", "client", "caller", "browser", "server", "api", "app", "worker", "queue", "db", "database",
  "github", "service", "system", "cli", "test", "tests",
}
# Words that say nothing about this code: a participant is not grounded by them alone
GENERIC_WORDS = GENERIC_PARTICIPANTS | {
  "handler", "manager", "controller", "module", "main", "core", "base", "helper", "util", "utils",
  "component", "layer", "process", "external", "internal", "local", "remote",
}

NAME = r"[A-Za-z_][\w.]*"
LABEL = r"[^<>;`\\]*"  # no markup, no statement separators
ALLOWED = [
  re.compile(r"autonumber"),
  re.compile(rf"(participant|actor)\s+{NAME}(\s+as\s+[^<>;{{}}`\\]+)?"),
  re.compile(rf"{NAME}\s*(->>|-->>|->|-->|-x|--x|-\)|--\))\s*[+-]?\s*{NAME}\s*:\s*{LABEL}"),
  re.compile(rf"(activate|deactivate)\s+{NAME}"),
  re.compile(rf"Note\s+(left of|right of|over)\s+{NAME}(\s*,\s*{NAME})?\s*:\s*{LABEL}", re.IGNORECASE),
  re.compile(rf"(loop|alt|opt|par|critical|break)(\s+{LABEL})?"),
  re.compile(rf"(else|and)(\s+{LABEL})?"),
  re.compile(r"end"),
]
DECLARED = re.compile(rf"^(?:participant|actor)\s+({NAME})")
MESSAGE = re.compile(rf"^({NAME})\s*(?:->>|-->>|->|-->|-x|--x|-\)|--\))\s*[+-]?\s*({NAME})\s*:")
OPENING_FENCE = re.compile(r"^```\s*(?:mermaid\b)?\s*")


def clean_diagram(text: str, bundle: EvidenceBundle) -> str | None:
  """The diagram if it passes the syntax and grounding checks, else None."""
  lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
  if lines and lines[0].startswith("```"):  # ```mermaid, or ```sequenceDiagram on one line
    first = OPENING_FENCE.sub("", lines[0], count=1)
    lines = [first, *lines[1:]] if first else lines[1:]
  lines = [line for line in lines if line != "```"]
  if not lines or lines[0] != "sequenceDiagram" or len(lines) > MAX_LINES:
    return None
  body = lines[1:]
  if not body or any("%%" in line for line in body):
    return None
  if not all(any(rule.fullmatch(line) for rule in ALLOWED) for line in body):
    return None
  participants: set[str] = set()
  for line in body:
    for pattern in (DECLARED, MESSAGE):
      found = pattern.match(line)
      if found:
        participants.update(found.groups())
  if not any(MESSAGE.match(line) for line in body):
    return None
  evidence = set(code_tokens("\n".join(f"{item.path or ''}\n{item.text}" for item in bundle.items)))
  named = [name for name in participants if name.lower() not in GENERIC_PARTICIPANTS]
  grounded = [name for name in named if is_grounded(name, evidence)]
  if not named or len(grounded) * 2 < len(named):
    return None
  return "\n".join(["sequenceDiagram", *("    " + line for line in body)])


def is_grounded(name: str, evidence: set[str]) -> bool:
  """The participant's name (its last part, for app.run) or a telling word of it is a word of
  the evidence: FlaskApp is grounded by "flask", BillingService is not by "service"."""
  if name.split(".")[-1].lower() in evidence:
    return True
  return any(len(word) >= 3 and word not in GENERIC_WORDS and word in evidence for word in code_tokens(name))


def make_diagram(meter: CostMeter, bundle: EvidenceBundle) -> str | None:
  if not any(item.kind == "hunk" for item in bundle.items):
    return None
  tag = data_tag(bundle)
  system = load_prompt(DIAGRAM_PROMPT).replace("{tag}", tag)
  answer = meter.complete(system, render_bundle(bundle, tag) + "\n\nDraw the diagram, or answer NONE.", MAX_OUTPUT_TOKENS).text
  if answer.strip().upper() == "NONE":
    return None
  return clean_diagram(answer, bundle)
