"""Compare the inputs the model saw recently with its training data (population stability index).

Reads the model inputs logged in pull_request_risks. Run it on a schedule (e.g. weekly cron):
  python -m scripts.drift_report               # PRs scored in the last 30 days
  python -m scripts.drift_report --days 7
"""
import argparse
from datetime import timedelta
from pathlib import Path

import joblib
from sqlalchemy import select

from app.core.config import settings
from app.core.time_utils import utc_now
from app.db.models import PullRequestRisk
from app.db.session import SessionLocal
from app.modules.ml.drift import drift_status, population_stability_index


def main() -> None:
  parser = argparse.ArgumentParser(description="Feature drift since training.")
  parser.add_argument("--days", type=int, default=30)
  args = parser.parse_args()

  path = Path(settings.risk_model_path)
  if not path.exists():
    raise SystemExit(f"No model at {path}")
  saved = joblib.load(path)
  bins = saved["metadata"]["feature_bins"]

  with SessionLocal() as db:
    inputs = db.scalars(
      select(PullRequestRisk.model_inputs).where(
        PullRequestRisk.model_version == saved["version"],
        PullRequestRisk.computed_at >= utc_now() - timedelta(days=args.days),
      )
    ).all()
  if not inputs:
    raise SystemExit(f"No PRs scored by {saved['version']} in the last {args.days} days")

  print(f"{len(inputs)} PRs scored by {saved['version']} in the last {args.days} days")
  for index, name in enumerate(saved["features"]):
    psi = population_stability_index(
      bins[name]["edges"], bins[name]["shares"], [row[index] for row in inputs]
    )
    print(f"  {name:28} PSI {psi:6.3f}  {drift_status(psi)}")


if __name__ == "__main__":
  main()
