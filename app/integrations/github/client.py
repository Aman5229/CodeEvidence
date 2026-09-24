import httpx

from app.core.config import settings

GITHUB_API_URL = "https://api.github.com"


class GitHubClient:
  """The only place in the app that talks to GitHub's REST API."""

  def __init__(self, token: str, timeout: float = 15.0) -> None:
    self._headers = {
      "Authorization": f"Bearer {token}",
      "Accept": "application/vnd.github+json",
    }
    self._timeout = timeout

  async def get_pull_request_files(self, repo_full_name: str, pr_number: int) -> list[dict]:
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pulls/{pr_number}/files"

    async with httpx.AsyncClient(timeout=self._timeout) as client:
      response = await client.get(url, headers=self._headers)
      response.raise_for_status()
      return response.json()


def get_github_client() -> GitHubClient:
  """FastAPI dependency: builds a client from settings (easy to replace in tests)."""
  return GitHubClient(token=settings.github_token)
