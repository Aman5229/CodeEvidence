import pytest


@pytest.fixture(autouse=True)
def fixed_llm_settings(monkeypatch):
  """Tests never depend on the LLM settings in your .env (e.g. a free local model priced at 0):
  costs, budgets and the evidence size are pinned to the defaults."""
  from app.core.config import settings

  monkeypatch.setattr(settings, "llm_input_usd_per_mtok", 3.0)
  monkeypatch.setattr(settings, "llm_output_usd_per_mtok", 15.0)
  monkeypatch.setattr(settings, "review_budget_usd", 0.25)
  monkeypatch.setattr(settings, "review_token_budget", 12_000)
