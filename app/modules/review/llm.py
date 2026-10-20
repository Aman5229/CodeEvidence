"""LLM providers behind one interface, plus cost accounting and a per-review budget.

- AnthropicProvider calls Claude. The key comes from the environment (ANTHROPIC_API_KEY).
- OpenAICompatibleProvider calls any server speaking the OpenAI chat API: a free local model
  with Ollama, or hosted services such as Groq or OpenRouter.
- FakeLLM returns canned answers: tests and CI never call a paid API.

Like the GitHub client, a provider makes one attempt per call. Retries, pauses and the
circuit breaker live in the job layer (LLMGuard reuses the GitHub guard's mechanisms).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import settings
from app.integrations.github.guard import RETRYABLE_STATUS_CODES, GitHubGuard

TIMEOUT_SECONDS = 60.0
LOCAL_TIMEOUT_SECONDS = 300.0  # a model on a laptop writes far slower than a hosted one


@dataclass(frozen=True)
class LLMResponse:
  text: str
  input_tokens: int
  output_tokens: int
  latency_ms: int


class LLMProvider(Protocol):
  model: str

  def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse: ...


class LLMError(Exception):
  """A failed LLM call. `transient` errors may succeed later; `retry_after` is set when the
  provider said how long to wait (rate limit)."""

  def __init__(self, message: str, *, transient: bool, retry_after: float | None = None) -> None:
    super().__init__(message)
    self.transient = transient
    self.retry_after = retry_after

  def __reduce__(self):
    # Celery copies exceptions between processes (pickle); keyword arguments need this
    return (_rebuild_llm_error, (str(self), self.transient, self.retry_after))


def _rebuild_llm_error(message: str, transient: bool, retry_after: float | None) -> "LLMError":
  return LLMError(message, transient=transient, retry_after=retry_after)


class BudgetExceeded(Exception):
  """The next call could take the review over its budget: stop cleanly instead."""


class AnthropicProvider:
  def __init__(self, api_key: str, model: str) -> None:
    import anthropic

    self.model = model
    self._anthropic = anthropic
    # max_retries=0: the job layer retries, so a failure is never retried at two levels
    self._client = anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=0)

  def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
    errors = self._anthropic
    started = time.perf_counter()
    try:
      message = self._client.messages.create(
        model=self.model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
      )
    except errors.RateLimitError as error:
      retry_after = error.response.headers.get("retry-after")
      raise LLMError(str(error), transient=True, retry_after=float(retry_after) if retry_after else 30.0) from error
    except (errors.APIConnectionError, errors.InternalServerError) as error:  # incl. timeouts, 5xx, overloaded
      raise LLMError(str(error), transient=True) from error
    except errors.APIStatusError as error:  # bad request, auth, not found: retrying will not help
      raise LLMError(str(error), transient=False) from error
    text = "".join(block.text for block in message.content if block.type == "text")
    return LLMResponse(
      text=text,
      input_tokens=message.usage.input_tokens,
      output_tokens=message.usage.output_tokens,
      latency_ms=round((time.perf_counter() - started) * 1000),
    )


class OpenAICompatibleProvider:
  """POST {base_url}/chat/completions, the format Ollama, Groq, OpenRouter and others accept."""

  def __init__(
    self, base_url: str, model: str, api_key: str = "", transport: httpx.BaseTransport | None = None
  ) -> None:
    self.model = model
    self._url = base_url.rstrip("/") + "/chat/completions"
    self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    self._transport = transport  # tests pass a fake transport; None means the real network

  def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
    started = time.perf_counter()
    body = {
      "model": self.model,
      "max_tokens": max_tokens,
      "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    try:
      with httpx.Client(timeout=LOCAL_TIMEOUT_SECONDS, transport=self._transport) as client:
        response = client.post(self._url, json=body, headers=self._headers)
    except httpx.TransportError as error:  # not running, connection refused, timeout
      raise LLMError(f"Cannot reach the LLM at {self._url}: {error}", transient=True) from error
    if response.status_code == 429:
      retry_after = response.headers.get("retry-after")
      raise LLMError("LLM rate limit", transient=True, retry_after=float(retry_after) if retry_after else 30.0)
    if response.status_code >= 400:
      raise LLMError(
        f"LLM answered {response.status_code}: {response.text[:300]}",
        transient=response.status_code in RETRYABLE_STATUS_CODES,
      )
    answer = response.json()
    usage = answer.get("usage") or {}
    text = answer["choices"][0]["message"]["content"] or ""
    return LLMResponse(
      text=text,
      input_tokens=usage.get("prompt_tokens", (len(system) + len(user)) // 4),
      output_tokens=usage.get("completion_tokens", len(text) // 4),
      latency_ms=round((time.perf_counter() - started) * 1000),
    )


class FakeLLM:
  """Answers from a list (one per call, in order) or a function of (system, user)."""

  model = "fake-llm"

  def __init__(self, answers: list[str] | Callable[[str, str], str]) -> None:
    self.answers = answers
    self.calls: list[tuple[str, str]] = []

  def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
    self.calls.append((system, user))
    if callable(self.answers):
      text = self.answers(system, user)
    else:
      text = self.answers[min(len(self.calls), len(self.answers)) - 1]
    return LLMResponse(text=text, input_tokens=(len(system) + len(user)) // 4, output_tokens=len(text) // 4, latency_ms=0)


@lru_cache(maxsize=1)
def get_llm() -> LLMProvider:
  if settings.llm_provider == "fake":
    return FakeLLM(lambda system, user: '{"findings": []}')
  if settings.llm_provider == "openai_compatible":
    return OpenAICompatibleProvider(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
  if not settings.anthropic_api_key:
    raise LLMError("ANTHROPIC_API_KEY is not set", transient=False)
  return AnthropicProvider(settings.anthropic_api_key, settings.llm_model)


def cost_usd(input_tokens: int, output_tokens: int) -> float:
  return (
    input_tokens * settings.llm_input_usd_per_mtok + output_tokens * settings.llm_output_usd_per_mtok
  ) / 1_000_000


class CostMeter:
  """Adds up tokens and cost of a review's calls, and refuses a call that could go over budget.

  Before each call the worst case is checked: the estimated prompt plus the full max_tokens of
  output. So the budget is never exceeded, at the price of sometimes stopping a little early.
  """

  def __init__(self, llm: LLMProvider, budget_usd: float) -> None:
    self.llm = llm
    self.budget_usd = budget_usd
    self.calls = self.input_tokens = self.output_tokens = self.latency_ms = 0
    self.cost_usd = 0.0

  def complete(self, system: str, user: str, max_tokens: int) -> LLMResponse:
    worst_case = cost_usd((len(system) + len(user)) // 4 + 1, max_tokens)
    if self.cost_usd + worst_case > self.budget_usd:
      raise BudgetExceeded(
        f"Next call could cost ${worst_case:.4f}; ${self.cost_usd:.4f} of ${self.budget_usd:.2f} already spent"
      )
    response = self.llm.complete(system, user, max_tokens)
    self.calls += 1
    self.input_tokens += response.input_tokens
    self.output_tokens += response.output_tokens
    self.latency_ms += response.latency_ms
    self.cost_usd += cost_usd(response.input_tokens, response.output_tokens)
    return response


class LLMGuard(GitHubGuard):
  """Rate-limit pause and circuit breaker for the LLM provider, shared by all workers."""

  name = "llm"
  label = "LLM"

  def rate_limit_wait(self, error: Exception) -> float | None:
    return error.retry_after if isinstance(error, LLMError) else None

  def is_transient(self, error: Exception) -> bool:
    return isinstance(error, LLMError) and error.transient and error.retry_after is None
