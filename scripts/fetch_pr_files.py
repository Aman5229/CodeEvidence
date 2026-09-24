"""Dev script: fetch a real PR's changed files from GitHub and print them.

Run from the project root:
  python -m scripts.fetch_pr_files
"""
import asyncio

from app.integrations.github.client import get_github_client


async def main():
  github = get_github_client()
  files = await github.get_pull_request_files("Aman5229/AI-Knowledgebase-Chatbot", 1)

  print(f"Got {len(files)} file(s):")
  for f in files:
    print(f"  {f['status']:10} {f['filename']}  (+{f['additions']}/-{f['deletions']})")


if __name__ == "__main__":
  asyncio.run(main())
