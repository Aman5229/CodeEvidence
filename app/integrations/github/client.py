import httpx

from app.core.config import settings

GITHUB_API_URL = "https://api.github.com"
FILES_PER_PAGE = 100  # GitHub's maximum page size
MAX_FILE_PAGES = 30  # GitHub returns at most 3000 files per PR (30 x 100)
PULLS_PER_PAGE = 100


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
    files: list[dict] = []

    async with httpx.AsyncClient(timeout=self._timeout) as client:
      for page in range(1, MAX_FILE_PAGES + 1):
        response = await client.get(
          url,
          headers=self._headers,
          params={"per_page": FILES_PER_PAGE, "page": page},
        )
        response.raise_for_status()
        batch = response.json()
        files.extend(batch)

        if len(batch) < FILES_PER_PAGE:
          break

    return files

  async def get_repository(self, repo_full_name: str) -> dict:
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}"

    async with httpx.AsyncClient(timeout=self._timeout) as client:
      response = await client.get(url, headers=self._headers)
      response.raise_for_status()
      return response.json()

  async def list_closed_pull_requests(self, repo_full_name: str, limit: int) -> list[dict]:
    """Most recently created closed PRs (merged and unmerged), newest first."""
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pulls"
    pulls: list[dict] = []
    page = 1

    async with httpx.AsyncClient(timeout=self._timeout) as client:
      while len(pulls) < limit:
        response = await client.get(
          url,
          headers=self._headers,
          params={"state": "closed", "per_page": PULLS_PER_PAGE, "page": page},
        )
        response.raise_for_status()
        batch = response.json()
        pulls.extend(batch)

        if len(batch) < PULLS_PER_PAGE:
          break
        page += 1

    return pulls[:limit]


def get_github_client() -> GitHubClient:
  """FastAPI dependency: builds a client from settings (easy to replace in tests)."""
  return GitHubClient(token=settings.github_token)
