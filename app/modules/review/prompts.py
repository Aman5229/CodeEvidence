"""Build the messages sent to the LLM, from versioned prompt files and the evidence bundle.

Prompt-injection defence: everything that comes from the PR (title, description, code) is
untrusted. It goes only in the user message, wrapped in a tag whose name contains a hash of
that same content. The PR's author would need to know the hash of their own text in advance
to close the tag and smuggle instructions outside it, which is not feasible. The system
prompt says to never follow instructions inside those tags.
"""

import hashlib
from functools import cache
from pathlib import Path

from app.modules.code.evidence import EvidenceBundle
from app.modules.review.findings import MAX_FINDINGS

PROMPTS_DIR = Path(__file__).parent / "prompts"
REVIEW_PROMPT = "review_v1"
SUMMARY_PROMPT = "summary_v1"
SUMMARY_MAX_WORDS = 80


@cache
def load_prompt(version: str) -> str:
  return (PROMPTS_DIR / f"{version}.md").read_text()


def data_tag(bundle: EvidenceBundle) -> str:
  content = "\0".join([bundle.title, bundle.description, *(item.text for item in bundle.items)])
  return "data-" + hashlib.sha256(content.encode()).hexdigest()[:12]


def render_bundle(bundle: EvidenceBundle, tag: str) -> str:
  parts = [
    f'<{tag} id="title">\n{bundle.title}\n</{tag}>',
    f'<{tag} id="description">\n{bundle.description}\n</{tag}>',
  ]
  for item in bundle.items:
    where = f' path="{item.path}"' if item.path else ""
    if item.start_line is not None:
      where += f' lines="{item.start_line}-{item.end_line}"'
    parts.append(f'<{tag} id="{item.id}" kind="{item.kind}"{where}>\n{item.text}\n</{tag}>')
  return "\n\n".join(parts)


def review_messages(bundle: EvidenceBundle, version: str = REVIEW_PROMPT) -> tuple[str, str]:
  tag = data_tag(bundle)
  system = load_prompt(version).replace("{tag}", tag).replace("{max_findings}", str(MAX_FINDINGS))
  user = render_bundle(bundle, tag) + "\n\nReview this pull request. Answer with the JSON object only."
  return system, user


def summary_messages(bundle: EvidenceBundle, version: str = SUMMARY_PROMPT) -> tuple[str, str]:
  tag = data_tag(bundle)
  hunks = [item for item in bundle.items if item.kind == "hunk"]
  trimmed = EvidenceBundle(title=bundle.title, description=bundle.description, items=hunks)
  system = load_prompt(version).replace("{tag}", tag).replace("{max_words}", str(SUMMARY_MAX_WORDS))
  return system, render_bundle(trimmed, tag) + "\n\nSummarise this pull request."
