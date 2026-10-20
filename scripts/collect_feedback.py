"""Read 👍/👎 reactions on published review comments into the feedback table.

GitHub sends no webhook for reactions, so they are polled. Safe to re-run: each reaction is
recorded once. Run it on a schedule (e.g. hourly cron):
  python -m scripts.collect_feedback
"""
import asyncio

from sqlalchemy import select

from app.db.models import Review
from app.db.session import SessionLocal
from app.integrations.github.client import get_github_client
from app.modules.review.feedback import collect_reactions


async def main() -> None:
  github = get_github_client()
  with SessionLocal() as db:
    reviews = db.scalars(select(Review).where(Review.published_at.is_not(None))).all()
    total = 0
    for review in reviews:
      total += await collect_reactions(db, github, review)
  print(f"{total} new reactions recorded from {len(reviews)} published reviews")


if __name__ == "__main__":
  asyncio.run(main())
