"""(Re)compute the risk score of every stored PR, repository by repository.

New PRs are scored by the worker automatically. Use this for data stored before scoring
existed, or after changing the rules.

Run from the project root:
  python -m scripts.score_pull_requests                    # every repository
  python -m scripts.score_pull_requests pallets/flask      # one repository
"""
import argparse
from collections import Counter

from sqlalchemy import func, select

from app.db.models import PullRequestRisk, Repository
from app.db.session import SessionLocal
from app.modules.risk.service import score_repository


def main() -> None:
  parser = argparse.ArgumentParser(description="Score stored pull requests.")
  parser.add_argument("repos", nargs="*", help="owner/name of each repository (default: all)")
  args = parser.parse_args()

  with SessionLocal() as db:
    query = select(Repository).order_by(Repository.id)
    if args.repos:
      query = query.where(Repository.full_name.in_(args.repos))
    for repository in db.scalars(query).all():
      scored = score_repository(db, repository.id)
      levels = Counter(
        dict(
          db.execute(
            select(PullRequestRisk.level, func.count())
            .where(PullRequestRisk.repository_id == repository.id)
            .group_by(PullRequestRisk.level)
          ).all()
        )
      )
      print(
        f"{repository.full_name}: {scored} PRs scored "
        f"(low {levels['low']}, medium {levels['medium']}, high {levels['high']})"
      )


if __name__ == "__main__":
  main()
