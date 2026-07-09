from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./jobtomatik.db"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "supersecretkey-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 days

    # AI is optional. The app should work for free with AI_PROVIDER=template.
    ai_provider: str = "template"  # template | anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # Email is optional. If SENDGRID_API_KEY is empty, emails are logged/mocked.
    sendgrid_api_key: str = ""
    from_email: str = "noreply@jobtomatik.com"

    # Optional integrations / local development.
    rapidapi_key: str = ""
    upload_dir: str = "uploads"
    dev_mock_jobs: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
