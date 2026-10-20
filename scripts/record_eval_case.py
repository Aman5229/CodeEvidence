"""Record a real review as a replayable evaluation case (eval/cases/<name>.json).

Runs the real LLM once on a stored PR and saves the evidence and the model's raw answers.
CI then replays those answers through the pipeline with no API calls. Label every proposed
finding in the file's "labels" (useful, wrong or not_grounded) before committing it.

  python -m scripts.record_eval_case 42 --name flask-session-fix
"""
import argparse
import asyncio
import json
from pathlib import Path

from app.core.config import settings
from app.db.models import PullRequest, PullRequestRisk
from app.db.session import SessionLocal
from app.integrations.github.client import get_github_client
from app.modules.code.embeddings import get_embedder
from app.modules.code.evidence import collect_evidence
from app.modules.review.findings import parse_findings
from app.modules.review.llm import CostMeter, LLMResponse, get_llm
from app.modules.review.pipeline import run_pipeline


class RecordingLLM:
  """Passes calls to the real provider and keeps every answer."""

  def __init__(self, llm) -> None:
    self.llm, self.model, self.answers = llm, llm.model, []

  def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
    response = self.llm.complete(system, user, max_tokens)
    self.answers.append(response.text)
    return response


async def record(pull_request_id: int, name: str) -> Path:
  with SessionLocal() as db:
    pull_request = db.get(PullRequest, pull_request_id)
    if pull_request is None:
      raise SystemExit(f"Pull request {pull_request_id} does not exist")
    bundle = await collect_evidence(db, get_github_client(), get_embedder(), pull_request)
    risk = db.get(PullRequestRisk, pull_request_id)
  recorder = RecordingLLM(get_llm())
  meter = CostMeter(recorder, settings.review_budget_usd)
  result = run_pipeline(meter, bundle, risk.level if risk else None)

  proposed = []
  for answer in recorder.answers[:-1]:  # the last answer is the summary
    try:
      proposed = parse_findings(answer).findings
    except ValueError:
      continue
  path = Path(f"eval/cases/{name}.json")
  path.write_text(json.dumps({
    "name": name,
    "note": f"Recorded from pull request {pull_request_id} with {recorder.model}",
    "risk_level": risk.level if risk else None,
    "title": bundle.title,
    "description": bundle.description,
    "evidence": [{**item, "new_lines": list(item["new_lines"])} for item in bundle.to_json()],
    "responses": recorder.answers,
    "labels": [{"path": f.path, "quote": f.quote, "label": None} for f in proposed],
  }, indent=2) + "\n")
  print(f"Saved {path}: {len(proposed)} findings proposed, {len(result.ranked)} shown, cost ${meter.cost_usd:.4f}")
  print("Now set each label to useful, wrong or not_grounded.")
  return path


def main() -> None:
  parser = argparse.ArgumentParser(description="Record a review for replay in CI.")
  parser.add_argument("pull_request_id", type=int)
  parser.add_argument("--name", required=True)
  args = parser.parse_args()
  asyncio.run(record(args.pull_request_id, args.name))


if __name__ == "__main__":
  main()
