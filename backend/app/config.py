from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "postgresql://jobtomatik:jobtomatik_pass@localhost:5432/jobtomatik"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "supersecretkey-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 days
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    ai_provider: str = "template"  # "template", "anthropic", "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash-lite"
    sendgrid_api_key: str = ""
    from_email: str = "noreply@jobtomatik.com"
    rapidapi_key: str = ""
    upload_dir: str = "uploads"

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
