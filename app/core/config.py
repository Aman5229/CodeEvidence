from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
  database_url: str
  redis_url: str
  celery_broker_url: str
  github_webhook_secret: str
  github_token: str
  cache_enabled: bool = True
  log_level: str = "INFO"
  # Token bucket per API key: up to `capacity` requests at once, refilled at `per_second`.
  rate_limit_capacity: int = 60
  rate_limit_per_second: float = 10.0
  # Browser origins allowed to call the API (the dashboard), comma-separated
  cors_origins: str = "http://localhost:5173"

  # ML risk model: served next to the rule score when this file exists
  risk_model_path: str = "models/risk_model.joblib"

  # Code retrieval: "local" runs an open-source embedding model; "fake" is for tests
  embedding_provider: str = "local"
  embedding_model: str = "BAAI/bge-small-en-v1.5"

  # AI review: "anthropic" calls Claude; "openai_compatible" calls a server speaking the
  # OpenAI chat API (Ollama on this machine for free, or Groq, OpenRouter...); "fake" returns
  # canned answers (tests, CI)
  llm_provider: str = "anthropic"
  anthropic_api_key: str = ""
  llm_model: str = "claude-sonnet-5-5"
  llm_base_url: str = "http://localhost:11434/v1"  # openai_compatible only; this is Ollama
  llm_api_key: str = ""  # openai_compatible only; Ollama needs none
  # USD per million tokens; check the provider's current price list (0 for a local model)
  llm_input_usd_per_mtok: float = 3.0
  llm_output_usd_per_mtok: float = 15.0
  review_budget_usd: float = 0.25  # per review; the review stops cleanly when it would go over
  review_token_budget: int = 12_000  # evidence sent to the model; lower it for small local models
  review_on_sync: bool = False  # review every PR automatically after its files are synced

  # Publishing reviews to GitHub: only to these repositories (owner/name, comma-separated)
  publish_repositories: str = ""

  # Chat about a PR ("Ask CodeEvidence"), in the dashboard and by @codeevidence on GitHub
  chat_budget_usd: float = 0.10  # per answer (also for turning feedback into a learning)
  chat_token_budget: int = 8_000  # evidence sent along with a question

  # Links back to the dashboard (commit statuses, replies on GitHub)
  dashboard_url: str = "http://localhost:5173"

  # Static analysis tools (ruff, semgrep, gitleaks) run on the changed files when installed
  tools_enabled: bool = True
  tool_timeout_seconds: int = 60
  model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
