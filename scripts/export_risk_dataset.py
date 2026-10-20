"""Export the training table (one row per closed PR) from the database to a CSV file.

Training reads this file, not the database, so a saved model can be reproduced from the
same file later (its SHA-256 is recorded in the model).

Run from the project root:
  python -m scripts.export_risk_dataset                       # writes data/risk_dataset.csv
  python -m scripts.export_risk_dataset --out /tmp/rows.csv
"""
import argparse
from collections import Counter
from pathlib import Path

from app.db.session import SessionLocal
from app.modules.ml.dataset import LABEL, build_rows, load_records, write_csv


def main() -> None:
  parser = argparse.ArgumentParser(description="Export the risk model's training data.")
  parser.add_argument("--out", type=Path, default=Path("data/risk_dataset.csv"))
  args = parser.parse_args()

  with SessionLocal() as db:
    rows = build_rows(load_records(db))
  write_csv(rows, args.out)

  rejected = sum(row[LABEL] for row in rows)
  print(f"{len(rows)} PRs written to {args.out} ({rejected} closed without merge)")
  for repository, count in sorted(Counter(row["repository"] for row in rows).items()):
    print(f"  {repository}: {count}")


if __name__ == "__main__":
  main()
