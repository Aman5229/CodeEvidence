"""Measure the AI reviewer on findings labelled by hand.

1. Export the shown findings of recent reviews for labelling:
     python -m scripts.evaluate_reviews export --limit 60
2. In eval/findings_gold.jsonl set "label" on each line to useful, wrong or not_grounded
   (rules in doc/evaluation.md). Leave it null to skip a finding.
3. Print the metrics table:
     python -m scripts.evaluate_reviews report
"""
import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.db.models import PullRequest, Repository, Review, ReviewFinding
from app.db.session import SessionLocal
from app.modules.review.evaluation import LABELS, Rate, percentile

GOLD = Path("eval/findings_gold.jsonl")


def export(limit: int) -> None:
  with SessionLocal() as db:
    rows = db.execute(
      select(ReviewFinding, Repository.full_name, PullRequest.number)
      .join(Review, Review.id == ReviewFinding.review_id)
      .join(PullRequest, PullRequest.id == Review.pull_request_id)
      .join(Repository, Repository.id == PullRequest.repository_id)
      .where(ReviewFinding.rank.is_not(None), Review.cached.is_(False))
      .order_by(ReviewFinding.id.desc())
      .limit(limit)
    ).all()
  existing = {}
  if GOLD.exists():  # keep labels already given
    existing = {item["finding_id"]: item for item in map(json.loads, GOLD.read_text().splitlines())}
  lines = []
  for finding, repository, number in rows:
    lines.append(existing.get(finding.id) or {
      "finding_id": finding.id,
      "url": f"https://github.com/{repository}/pull/{number}/files",
      "path": finding.path, "line": finding.line, "severity": finding.severity,
      "claim": finding.claim, "quote": finding.quote, "label": None,
    })
  GOLD.parent.mkdir(exist_ok=True)
  GOLD.write_text("".join(json.dumps(line) + "\n" for line in lines))
  print(f"{len(lines)} findings in {GOLD}; label each one: {', '.join(LABELS)}")


def report() -> None:
  labelled = [item for item in map(json.loads, GOLD.read_text().splitlines()) if item.get("label")]
  unknown = {item["label"] for item in labelled} - set(LABELS)
  if unknown:
    raise SystemExit(f"Unknown labels: {unknown}")
  with SessionLocal() as db:
    review_ids = set(db.scalars(select(ReviewFinding.review_id).where(ReviewFinding.id.in_([i["finding_id"] for i in labelled]))))
    reviews = db.scalars(select(Review).where(Review.id.in_(review_ids), Review.cached.is_(False))).all()
    proposed = db.scalars(select(ReviewFinding).where(ReviewFinding.review_id.in_(review_ids))).all()

  n = len(labelled)
  count = {label: sum(item["label"] == label for item in labelled) for label in LABELS}
  latencies = [review.latency_ms for review in reviews]
  costs = [review.cost_usd for review in reviews]
  print(f"Labelled findings: {n}, from {len(reviews)} reviews\n")
  print("| Metric | Value |\n|---|---|")
  print(f"| Precision (useful / shown) | {Rate(count['useful'], n)} |")
  print(f"| Grounded rate (not 'not_grounded') | {Rate(n - count['not_grounded'], n)} |")
  print(f"| Hallucination rate after verification | {Rate(count['not_grounded'], n)} |")
  print(f"| Dropped by the verifier (of all proposed) | {Rate(sum(f.status == 'dropped' for f in proposed), len(proposed))} |")
  print(f"| Latency p50 / p95 | {percentile(latencies, 0.5)} / {percentile(latencies, 0.95)} ms |")
  print(f"| Cost per review (mean) | ${sum(costs) / max(1, len(costs)):.4f} |")


def main() -> None:
  parser = argparse.ArgumentParser(description="Review quality evaluation.")
  sub = parser.add_subparsers(dest="command", required=True)
  export_parser = sub.add_parser("export", help="write findings to label")
  export_parser.add_argument("--limit", type=int, default=60)
  sub.add_parser("report", help="print the metrics table")
  args = parser.parse_args()
  if args.command == "export":
    export(args.limit)
  else:
    report()


if __name__ == "__main__":
  main()
