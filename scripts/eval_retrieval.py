"""Measure retrieval on a hand-labelled set: recall@k and MRR for vector, keyword and hybrid.

1. Write a labelling file with hunks from stored PRs (the repositories must be indexed):
     python -m scripts.eval_retrieval sample --count 30
2. For each line of eval/retrieval_gold.jsonl, fill "relevant" with the code a reviewer would
   want to see for that hunk: [{"path": "src/flask/app.py", "name": "Flask.make_response"}].
   "name" may be null to accept any chunk of that file. Leave out hunks with nothing relevant.
3. Measure:
     python -m scripts.eval_retrieval report
"""
import argparse
import json
import random
from pathlib import Path

from sqlalchemy import exists, select

from app.db.models import CodeChunk, PullRequest, PullRequestFile, Repository
from app.db.session import SessionLocal
from app.modules.code.diff import parse_patch
from app.modules.code.embeddings import get_embedder
from app.modules.code.filters import detect_language, skip_reason
from app.modules.code.retrieval import MODES, recall_at_k, reciprocal_rank, retrieve

GOLD = Path("eval/retrieval_gold.jsonl")
KS = (1, 3, 5, 10)


def sample(count: int, seed: int) -> None:
  with SessionLocal() as db:
    rows = db.execute(
      select(Repository.full_name, PullRequest.number, PullRequestFile.path, PullRequestFile.patch)
      .join(PullRequest, PullRequest.id == PullRequestFile.pull_request_id)
      .join(Repository, Repository.id == PullRequest.repository_id)
      .where(exists().where(CodeChunk.repository_id == Repository.id), PullRequestFile.patch.is_not(None))
    ).all()
  candidates = [
    {"repository": repo, "pull_request": number, "path": path, "hunk": hunk.text(), "relevant": []}
    for repo, number, path, patch in rows
    if detect_language(path) and not skip_reason(path)
    for hunk in parse_patch(patch)
    if 3 <= len(hunk.added) <= 40
  ]
  random.Random(seed).shuffle(candidates)
  GOLD.parent.mkdir(exist_ok=True)
  GOLD.write_text("".join(json.dumps(item) + "\n" for item in candidates[:count]))
  print(f"Wrote {min(count, len(candidates))} hunks to {GOLD}: fill in 'relevant' for each")


def report() -> None:
  gold = [json.loads(line) for line in GOLD.read_text().splitlines() if line.strip()]
  gold = [item for item in gold if item["relevant"]]
  if not gold:
    raise SystemExit(f"No labelled hunks in {GOLD}")
  embedder = get_embedder()
  with SessionLocal() as db:
    repository_ids = dict(db.execute(select(Repository.full_name, Repository.id)).all())
    print(f"{len(gold)} labelled hunks, embedding model {embedder.model_name}\n")
    print("| Mode | " + " | ".join(f"Recall@{k}" for k in KS) + " | MRR |")
    print("|---|" + "---|" * (len(KS) + 1))
    for mode in MODES:
      recalls = {k: 0.0 for k in KS}
      mrr = 0.0
      for item in gold:
        found = retrieve(db, embedder, repository_ids[item["repository"]], f"{item['path']}\n{item['hunk']}", k=max(KS), mode=mode)
        relevant = {(r["path"], r.get("name")) for r in item["relevant"]}
        # A hit is a chunk of a relevant file whose name matches, or any chunk when no name is given
        ranked = [
          next((key for key in relevant if key[0] == chunk.path and key[1] in (None, chunk.name)), None)
          for chunk in found
        ]
        ranked_keys = [key or f"miss-{i}" for i, key in enumerate(ranked)]
        for k in KS:
          recalls[k] += recall_at_k(ranked_keys, relevant, k)
        mrr += reciprocal_rank(ranked_keys, relevant)
      row = [f"{recalls[k] / len(gold):.2f}" for k in KS]
      print(f"| {mode} | " + " | ".join(row) + f" | {mrr / len(gold):.2f} |")


def main() -> None:
  parser = argparse.ArgumentParser(description="Retrieval evaluation.")
  sub = parser.add_subparsers(dest="command", required=True)
  sample_parser = sub.add_parser("sample", help="write hunks to label")
  sample_parser.add_argument("--count", type=int, default=30)
  sample_parser.add_argument("--seed", type=int, default=42)
  sub.add_parser("report", help="measure recall@k and MRR")
  args = parser.parse_args()
  if args.command == "sample":
    sample(args.count, args.seed)
  else:
    report()


if __name__ == "__main__":
  main()
