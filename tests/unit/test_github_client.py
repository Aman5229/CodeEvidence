"""GitHubClient: timeouts, redirects for renamed repositories, one attempt per call."""

import asyncio
import json

import httpx

from app.integrations.github.client import TIMEOUT, GitHubClient, is_not_found


def client_with(handler) -> GitHubClient:
  return GitHubClient(token="t", transport=httpx.MockTransport(handler))


def test_connect_timeout_is_short_and_read_timeout_longer():
  assert TIMEOUT.connect == 5.0
  assert TIMEOUT.read == 15.0


def test_renamed_repository_redirect_is_followed():
  def github(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/repos/encode/starlette":
      return httpx.Response(301, headers={"location": "https://api.github.com/repositories/42"})
    return httpx.Response(200, json={"id": 42, "full_name": "Kludex/starlette"})

  repo = asyncio.run(client_with(github).get_repository("encode/starlette"))

  assert repo["full_name"] == "Kludex/starlette"


def test_a_failure_is_raised_after_one_attempt():
  """Retries belong to the job layer, so the client must not retry on its own."""
  calls = []

  def github(request: httpx.Request) -> httpx.Response:
    calls.append(request)
    return httpx.Response(503)

  try:
    asyncio.run(client_with(github).get_repository("octo/demo"))
  except httpx.HTTPStatusError as error:
    assert error.response.status_code == 503
  else:
    raise AssertionError("expected HTTPStatusError")
  assert len(calls) == 1


def test_token_is_sent():
  seen = []

  def github(request: httpx.Request) -> httpx.Response:
    seen.append(request.headers["authorization"])
    return httpx.Response(200, json={})

  asyncio.run(client_with(github).get_repository("octo/demo"))

  assert seen == ["Bearer t"]


# ---------- files, comparisons, comments and statuses ----------

def test_get_file_decodes_the_content_and_is_none_when_missing():
  def github(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/repos/octo/demo/contents/docs/CLAUDE.md":
      assert request.url.params["ref"] == "main"
      return httpx.Response(200, json={"type": "file", "sha": "s1", "content": "aGVs\nbG8=\n", "encoding": "base64"})
    if request.url.path == "/repos/octo/demo/contents/src":
      return httpx.Response(200, json=[{"type": "file", "name": "a.py"}])  # a folder answers a list
    return httpx.Response(404, json={"message": "Not Found"})

  client = client_with(github)

  assert asyncio.run(client.get_file("octo/demo", "docs/CLAUDE.md", "main")) == {"sha": "s1", "content": b"hello"}
  assert asyncio.run(client.get_file("octo/demo", ".codeevidence.yaml", "main")) is None
  assert asyncio.run(client.get_file("octo/demo", "src", "main")) is None


def test_compare_commits_asks_for_base_three_dots_head():
  seen = []

  def github(request: httpx.Request) -> httpx.Response:
    seen.append(request.url.path)
    return httpx.Response(200, json={"status": "ahead", "files": []})

  assert asyncio.run(client_with(github).compare_commits("octo/demo", "a" * 40, "b" * 40))["status"] == "ahead"
  assert seen == [f"/repos/octo/demo/compare/{'a' * 40}...{'b' * 40}"]


def test_comment_calls_use_the_right_methods_and_paths():
  seen = []

  def github(request: httpx.Request) -> httpx.Response:
    seen.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
    return httpx.Response(200 if request.method == "PATCH" else 201, json={"id": 1})

  client = client_with(github)
  asyncio.run(client.create_issue_comment("octo/demo", 7, "hi"))
  asyncio.run(client.update_issue_comment("octo/demo", 55, "edited"))
  asyncio.run(client.reply_to_review_comment("octo/demo", 7, 99, "answer"))

  assert seen == [
    ("POST", "/repos/octo/demo/issues/7/comments", {"body": "hi"}),
    ("PATCH", "/repos/octo/demo/issues/comments/55", {"body": "edited"}),
    ("POST", "/repos/octo/demo/pulls/7/comments/99/replies", {"body": "answer"}),
  ]


def test_commit_status_description_is_cut_to_githubs_limit():
  sent = {}

  def github(request: httpx.Request) -> httpx.Response:
    sent.update(path=request.url.path, body=json.loads(request.content))
    return httpx.Response(201, json={"id": 1})

  asyncio.run(client_with(github).create_commit_status(
    "octo/demo", "c" * 40, state="failure", description="x" * 300, context="codeevidence/review", target_url="http://dash"
  ))

  assert sent["path"] == f"/repos/octo/demo/statuses/{'c' * 40}"
  assert len(sent["body"]["description"]) == 140
  assert (sent["body"]["state"], sent["body"]["context"]) == ("failure", "codeevidence/review")


def test_is_not_found():
  request = httpx.Request("GET", "https://api.github.com/x")

  assert is_not_found(httpx.HTTPStatusError("404", request=request, response=httpx.Response(404, request=request)))
  assert not is_not_found(httpx.HTTPStatusError("500", request=request, response=httpx.Response(500, request=request)))
  assert not is_not_found(ValueError())
