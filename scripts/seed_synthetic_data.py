"""Fill the database with synthetic repositories, pull requests and files.

Used to measure caching and query speed at a realistic volume.
Repeatable: the same seed gives the same data, and old synthetic rows are deleted first.

Run from the project root:
  python -m scripts.seed_synthetic_data                              # 10 repos x 10,000 PRs
  python -m scripts.seed_synthetic_data --repos 2 --prs-per-repo 500
"""

import argparse
import random
import time
from collections.abc import Iterator
from datetime import datetime, timezone, timedelta

from sqlalchemy import delete, insert, select
from sqlalchemy.orm import  Session

from app.db.models import PullRequest, PullRequestFile, Repository
from app.db.session import SessionLocal



OWNER = "synthetic"
BATCH_SIZE = 5_000
START = datetime(2024, 1, 1, tzinfo=timezone.utc)
TWO_YEARS_IN_MINUTES = 2 * 365 * 24 * 60

HUMANS = [f"dev{i}" for i in range(500)]
BOTS = ["dependabot[bot]", "renovate[bot]", "pre-commit-ci[bot]"]


def delete_synthetic_data(db: Session) -> None:
  repo_ids = select(Repository.id).where(Repository.owner == OWNER)
  pr_ids = select(PullRequest.id).where(PullRequest.repository_id.in_(repo_ids))
  db.execute(delete(PullRequestFile).where(PullRequestFile.pull_request_id.in_(pr_ids)))
  db.execute(delete(PullRequest).where(PullRequest.repository_id.in_(repo_ids)))
  db.execute(delete(Repository).where(Repository.owner == OWNER))


def insert_repository(db: Session, number: int) -> int:
  row = {
    "github_repo_id": 9_000_000_000 + number,  # far above real GitHub ids
    "owner": OWNER,
    "full_name": f"{OWNER}/repo-{number}",
    "default_branch": "main",
    "html_url": f"https://example.com/{OWNER}/repo-{number}",
    "is_private": False,
    "created_at": START,
    "updated_at": START,
    "ingested_at": START,
    "last_synced_at": START,
  }
  return db.scalar(insert(Repository).values(**row).returning(Repository.id))


def make_pull_request(rng: random.Random, repository_id: int, number: int) -> dict:
  created = START + timedelta(minutes=rng.randint(0, TWO_YEARS_IN_MINUTES))
  author = rng.choice(BOTS) if rng.random() < 0.10 else rng.choice(HUMANS)
  is_open = rng.random() < 0.10
  closed = None if is_open else created + timedelta(hours=rng.lognormvariate(1.5, 2.0))
  merged = closed if closed is not None and rng.random() < 0.35 else None
  return {
    "repository_id": repository_id,
    "github_pr_id": number,
    "number": number,
    "title": f"Synthetic change {number}",
    "author_login": author,
    "base_branch": "main",
    "head_branch": f"feature-{number}",
    "base_sha": "a" * 40,
    "head_sha": "b" * 40,
    "status": "open" if is_open else "closed",
    "created_at": created,
    "updated_at": closed or created,
    "closed_at": closed,
    "merged_at": merged,
    "ingested_at": created,
  }



def make_files(rng: random.Random, pull_request_id: int) -> list[dict]:
  rows = []
  for i in range(1 + int(rng.expovariate(1 / 2.5))):  # mean about 3 files
    additions = int(rng.lognormvariate(2.0, 1.5))
    deletions = int(rng.lognormvariate(1.0, 1.5))
    rows.append({
      "pull_request_id": pull_request_id,
      "path": f"src/module_{i}.py",
      "status": "modified",
      "additions": additions,
      "deletions": deletions,
      "changes": additions + deletions,
      "patch": "@@ -1,2 +1,2 @@\n-old line\n+new line",
      "patch_truncated": False,
      "is_stale": False,
      "created_at": START,
    })
  return rows


def batches(rows: list[dict]) -> Iterator[list[dict]]:
  for start in range(0, len(rows), BATCH_SIZE):
    yield rows[start:start + BATCH_SIZE]


def seed(db: Session, repos: int, prs_per_repo: int, random_seed: int = 42) -> None:
  rng = random.Random(random_seed)
  delete_synthetic_data(db)

  for repo_number in range(1, repos + 1):
    repository_id = insert_repository(db, repo_number)
    pull_requests = [
      make_pull_request(rng, repository_id, number) for number in range(1, prs_per_repo + 1)
    ]
    for batch in batches(pull_requests):
      pull_request_ids = db.scalars(
        insert(PullRequest).returning(PullRequest.id, sort_by_parameter_order=True),
        batch,
      ).all()
      files = [row for pr_id in pull_request_ids for row in make_files(rng, pr_id)]
      db.execute(insert(PullRequestFile), files)
    db.commit()  # one repository at a time
    print(f"  {OWNER}/repo-{repo_number}: {prs_per_repo:,} PRs")


def main() -> None:
  parser = argparse.ArgumentParser(description="Seed synthetic PR data.")
  parser.add_argument("--repos", type=int, default=10)
  parser.add_argument("--prs-per-repo", type=int, default=10_000)
  args = parser.parse_args()

  started = time.monotonic()
  db = SessionLocal()
  try:
    seed(db, args.repos, args.prs_per_repo)
  finally:
    db.close()
  print(f"Seeded {args.repos * args.prs_per_repo:,} PRs in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
  main()