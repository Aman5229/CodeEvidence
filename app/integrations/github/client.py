import base64

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

  async def get_tree(self, repo_full_name: str, ref: str) -> list[dict]:
    """Every file of the repository at `ref` (path, blob sha, size). GitHub stops at about
    100,000 entries and sets `truncated`; that is far more than we index."""
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/git/trees/{ref}"

    async with self._http() as client:
      response = await client.get(url, headers=self._headers, params={"recursive": "1"})
      response.raise_for_status()
      return [entry for entry in response.json()["tree"] if entry["type"] == "blob"]

  async def get_blob(self, repo_full_name: str, blob_sha: str) -> bytes:
    """A file's raw bytes by content hash (base64 in GitHub's answer)."""
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/git/blobs/{blob_sha}"

    async with self._http() as client:
      response = await client.get(url, headers=self._headers)
      response.raise_for_status()
      body = response.json()
      if body.get("encoding") != "base64":
        return body["content"].encode("utf-8")
      return base64.b64decode(body["content"])

  async def create_review(
    self, repo_full_name: str, pr_number: int, *, commit_id: str, body: str, comments: list[dict]
  ) -> dict:
    """Post a review with inline comments. Each comment: path, line (in the new file), side
    "RIGHT", body. event COMMENT: it neither approves nor blocks the PR."""
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pulls/{pr_number}/reviews"

    async with self._http() as client:
      response = await client.post(
        url,
        headers=self._headers,
        json={"commit_id": commit_id, "body": body, "event": "COMMENT", "comments": comments},
      )
      response.raise_for_status()
      return response.json()

  async def list_review_comments(self, repo_full_name: str, pr_number: int) -> list[dict]:
    """Every inline review comment on the PR, from anyone."""
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pulls/{pr_number}/comments"
    comments: list[dict] = []

    async with self._http() as client:
      for page in range(1, MAX_FILE_PAGES + 1):
        response = await client.get(url, headers=self._headers, params={"per_page": 100, "page": page})
        response.raise_for_status()
        batch = response.json()
        comments.extend(batch)
        if len(batch) < 100:
          break

    return comments

  async def list_comment_reactions(self, repo_full_name: str, comment_id: int) -> list[dict]:
    """Reactions (+1, -1, ...) on one review comment. GitHub sends no webhook for these."""
    url = f"{GITHUB_API_URL}/repos/{repo_full_name}/pulls/comments/{comment_id}/reactions"

    async with self._http() as client:
      response = await client.get(url, headers=self._headers, params={"per_page": 100})
      response.raise_for_status()
      return response.json()


def get_github_client() -> GitHubClient:
  """FastAPI dependency: builds a client from settings (easy to replace in tests)."""
  return GitHubClient(token=settings.github_token)
