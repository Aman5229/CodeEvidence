"""GitHubClient: timeouts, redirects for renamed repositories, one attempt per call."""

import asyncio

import httpx

from app.integrations.github.client import TIMEOUT, GitHubClient


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
