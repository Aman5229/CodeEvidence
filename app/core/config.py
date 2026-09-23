from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    github_webhook_secret: str
    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()