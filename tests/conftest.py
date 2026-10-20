import pytest


@pytest.fixture(autouse=True)
def fixed_llm_settings(monkeypatch):
  """Tests never depend on the settings in your .env (e.g. a free local model priced at 0):
  costs, budgets, the evidence size and links are pinned to the defaults."""
  from app.core.config import settings

  monkeypatch.setattr(settings, "llm_input_usd_per_mtok", 3.0)
  monkeypatch.setattr(settings, "llm_output_usd_per_mtok", 15.0)
  monkeypatch.setattr(settings, "review_budget_usd", 0.25)
  monkeypatch.setattr(settings, "review_token_budget", 12_000)
  monkeypatch.setattr(settings, "chat_budget_usd", 0.10)
  monkeypatch.setattr(settings, "chat_token_budget", 8_000)
  monkeypatch.setattr(settings, "dashboard_url", "http://localhost:5173")
  # Static analysis tools are off unless a test turns them on: results must not depend on
  # which tools happen to be installed on the machine running the tests
  monkeypatch.setattr(settings, "tools_enabled", False)
