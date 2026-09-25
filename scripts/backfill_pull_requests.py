"""Load recent closed PRs from public GitHub repositories into the database.

Run from the project root:
  python -m scripts.backfill_pull_requests                     # default repos, 60 PRs each
  python -m scripts.backfill_pull_requests pallets/flask --max-prs 20
"""
import argparse
import asyncio
import logging

import httpx

from app.db.session import SessionLocal
from app.integrations.github.client import get_github_client
from app.modules.ingestion.backfill import backfill_repository

DEFAULT_REPOS = [
  "fastapi/fastapi",
  "pallets/flask",
  "psf/requests",
  "encode/httpx",
  "pydantic/pydantic",
]


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(description="Backfill closed PRs from GitHub.")
  parser.add_argument("repos", nargs="*", default=DEFAULT_REPOS, help="owner/name of each repo")
  parser.add_argument("--max-prs", type=int, default=60, help="closed PRs to load per repo")
  return parser.parse_args()


async def main() -> None:
  args = parse_args()
  logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

  github = get_github_client()
  db = SessionLocal()
  try:
    for repo_full_name in args.repos:
      print(f"Backfilling {repo_full_name} (up to {args.max_prs} PRs)...")
      result = await backfill_repository(db, github, repo_full_name, args.max_prs)
      print(f"  stored={result.stored}  skipped={result.skipped}  failed={result.failed}")
  except httpx.HTTPStatusError as error:
    print(f"\nStopped: GitHub returned {error.response.status_code} ({error.request.url}).")
    print("If this is a rate limit, wait a while and re-run: stored PRs are skipped.")
  finally:
    db.close()


if __name__ == "__main__":
  asyncio.run(main())
