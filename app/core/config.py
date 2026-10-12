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
  model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
