import httpx

from app.core.config import settings

GITHUB_API_URL = "https://api.github.com"
FILES_PER_PAGE = 100  # GitHub's maximum page size
MAX_FILE_PAGES = 30  # GitHub returns at most 3000 files per PR (30 x 100)
PULLS_PER_PAGE = 100


# Fail fast when GitHub cannot be reached; allow slower answers once connected.
TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class GitHubClient:
  """The only place in the app that talks to GitHub's REST API.

  It makes one attempt per call. Retries, rate-limit pauses and the circuit breaker live in
  the job layer (app/jobs.py and guard.py), so a failure is never retried at two levels.
  """

  def __init__(self, token: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
    self._headers = {
      "Authorization": f"Bearer {token}",
      "Accept": "application/vnd.github+json",
    }
    self._transport = transport  # tests pass a fake transport; None means the real network

  def _http(self) -> httpx.AsyncClient:
    # follow_redirects: a renamed repository answers 301 with its new location
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, transport=self._transport)

  async def get_pull_request_files(self, repo_full_name: str, pr_number: int) -> list[dict]:
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pulls/{pr_number}/files"
    files: list[dict] = []

    async with self._http() as client:
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

    async with self._http() as client:
      response = await client.get(url, headers=self._headers)
      response.raise_for_status()
      return response.json()

  async def list_closed_pull_requests(self, repo_full_name: str, limit: int) -> list[dict]:
    """Most recently created closed PRs (merged and unmerged), newest first."""
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pulls"
    pulls: list[dict] = []
    page = 1

    async with self._http() as client:
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
