from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./jobtomatik.db"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "supersecretkey-change-in-production"
    answer_vault_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080

    # AI is optional. The app works for free with AI_PROVIDER=template.
    ai_provider: str = "template"  # template | anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # Email is optional. If SENDGRID_API_KEY is empty, email applications are prepared but not sent.
    sendgrid_api_key: str = ""
    from_email: str = "mohamed@melato.ca"

    # Optional integrations / local development.
    rapidapi_key: str = ""
    upload_dir: str = "uploads"
    dev_mock_jobs: bool = False

    # Defense-in-depth gate for any non-dry-run application attempt.
    # Keep disabled until the active adapter has passed supervised certification.
    allow_real_application_submit: bool = False

    # Additional scoped gate for the Greenhouse supervised real-submission pilot.
    # Both this and ALLOW_REAL_APPLICATION_SUBMIT must be true, and every live
    # attempt still requires a one-time exact-payload approval.
    greenhouse_supervised_pilot_enabled: bool = False
    supervised_approval_ttl_minutes: int = 20
    supervised_approval_max_ttl_minutes: int = 60

    # Dry runs retain human-verification boundaries automatically. This flag also
    # enables retained-browser handoffs for explicitly approved non-dry runs.
    enable_resumable_handoffs: bool = False

    # Verified read-only Phase A baseline plus writable Phase B runtime ledger.
    # Readiness merges both sources. Runtime ingestion never rewrites the baseline.
    greenhouse_pilot_baseline_path: str = "evidence/greenhouse-phase-a-baseline.csv"
    greenhouse_pilot_ledger_path: str = "evidence/greenhouse-pilot-ledger.jsonl"
    greenhouse_pilot_readiness_json_path: str = "evidence/greenhouse-pilot-readiness.json"
    greenhouse_pilot_readiness_markdown_path: str = "evidence/greenhouse-pilot-readiness.md"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
