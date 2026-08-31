from functools import lru_cache
from typing import List, Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_SECRET_KEY = "supersecretkey-change-in-production"
PLACEHOLDER_SECRET_MARKERS = (
    "change-me",
    "replace-with",
    "supersecretkey",
    "development-secret",
)


class Settings(BaseSettings):
    app_environment: Literal["development", "test", "production"] = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "APP_ENVIRONMENT"),
    )
    enable_api_docs: bool = True

    database_url: str = "sqlite:///./jobtomatik.db"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = DEFAULT_SECRET_KEY
    answer_vault_key: str = ""
    # Separate trust root for signed certified-autonomous release manifests.
    # It must remain empty until an operator intentionally configures a release key.
    autonomy_certification_signing_key: str = ""
    algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=10080, ge=5, le=43200)

    # Comma-separated browser origins allowed to call the API with credentials.
    # These defaults cover Vite, the local browser UI, and Capacitor Android.
    cors_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "https://localhost,"
        "http://localhost,"
        "capacitor://localhost"
    )

    # AI is optional. The app works for free with AI_PROVIDER=template.
    ai_provider: str = "template"  # template | anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # Email is optional. If SENDGRID_API_KEY is empty, email applications are prepared but not sent.
    sendgrid_api_key: str = ""
    from_email: str = "noreply@jobtomatik.com"

    # Optional integrations / local development.
    rapidapi_key: str = ""
    upload_dir: str = "uploads"
    dev_mock_jobs: bool = False

    # Persistent local browser used to resolve job-board listings and run ATS forms.
    # The code default remains headless for CI. Local XFCE installs can set
    # APPLICATION_BROWSER_HEADLESS=false and log in once to the dedicated profile.
    application_browser_profile_dir: str = "browser_profiles/jobtomatik-operator"
    application_browser_headless: bool = True
    application_browser_executable: str = ""
    # Android-only installs may keep Chromium running natively in Termux and let
    # the Ubuntu PRoot worker attach over Chrome DevTools Protocol. When set,
    # JobTomatik never launches or terminates the external browser process.
    application_browser_cdp_endpoint: str = ""
    # Keep target resolution nonblocking for headless and solo-worker deployments.
    # A positive value is an explicit opt-in that occupies the current worker task.
    application_target_human_wait_seconds: int = Field(default=0, ge=0, le=3600)

    # Defense-in-depth gate for any non-dry-run application attempt.
    # Keep disabled until the active adapter has passed supervised certification.
    allow_real_application_submit: bool = False

    # Independent defense-in-depth gate for recruiter/hiring-team email follow-ups.
    # Approval of an application submission never implies permission to contact a person.
    allow_real_followup_send: bool = False
    supervised_followup_max_schedule_days: int = Field(default=30, ge=1, le=90)

    # Platform-scoped supervised real-submission pilots. The global flag, the
    # matching platform flag, and a one-time exact-payload approval are required.
    greenhouse_supervised_pilot_enabled: bool = False
    lever_supervised_pilot_enabled: bool = False
    supervised_approval_ttl_minutes: int = Field(default=20, ge=1, le=60)
    supervised_approval_max_ttl_minutes: int = Field(default=60, ge=1, le=240)

    # Dry runs retain human-verification boundaries automatically. This flag also
    # enables retained-browser handoffs for explicitly approved non-dry runs.
    enable_resumable_handoffs: bool = False

    # Verified read-only Phase A baseline plus writable Phase B runtime ledger.
    # Readiness merges both sources. Runtime ingestion never rewrites the baseline.
    greenhouse_pilot_baseline_path: str = "evidence/greenhouse-phase-a-baseline.csv"
    greenhouse_pilot_ledger_path: str = "evidence/greenhouse-pilot-ledger.jsonl"
    greenhouse_pilot_readiness_json_path: str = "evidence/greenhouse-pilot-readiness.json"
    greenhouse_pilot_readiness_markdown_path: str = "evidence/greenhouse-pilot-readiness.md"

    # Lever evidence is isolated from Greenhouse. The baseline may remain absent
    # until retained Phase A artifacts are indexed; absence counts as zero evidence.
    lever_pilot_baseline_path: str = "evidence/lever-phase-a-baseline.csv"
    lever_pilot_ledger_path: str = "evidence/lever-pilot-ledger.jsonl"
    lever_pilot_readiness_json_path: str = "evidence/lever-pilot-readiness.json"
    lever_pilot_readiness_markdown_path: str = "evidence/lever-pilot-readiness.md"
    lever_phase_b_launch_path: str = "evidence/lever-phase-b-launch.json"

    @property
    def cors_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_environment == "production"

    @property
    def uses_placeholder_secret(self) -> bool:
        normalized = self.secret_key.strip().lower()
        return (
            len(self.secret_key.encode("utf-8")) < 32
            or normalized == DEFAULT_SECRET_KEY
            or any(marker in normalized for marker in PLACEHOLDER_SECRET_MARKERS)
        )

    @model_validator(mode="after")
    def validate_runtime_security(self) -> "Settings":
        if "*" in self.cors_origin_list:
            raise ValueError("CORS_ORIGINS cannot contain '*' when credentialed requests are enabled")

        if self.supervised_approval_ttl_minutes > self.supervised_approval_max_ttl_minutes:
            raise ValueError(
                "SUPERVISED_APPROVAL_TTL_MINUTES cannot exceed "
                "SUPERVISED_APPROVAL_MAX_TTL_MINUTES"
            )

        # The supervised Lever window never trusts a generic environment label. API,
        # worker, and Beat must prove they are children of the real Android manager,
        # that the manager carries this restart's random capability token, that their
        # runtime and expected revisions match, and that the owner-bound marker matches
        # the same token/revision. The child processes keep their existing env -i
        # isolation. This capability never creates the separate one-time application
        # approval required for a final submission.
        from app.services.supervised_runtime_mode import (
            managed_android_lever_runtime_capability_active,
        )

        if managed_android_lever_runtime_capability_active():
            if self.greenhouse_supervised_pilot_enabled:
                raise ValueError(
                    "Greenhouse supervised pilot cannot be enabled during the ephemeral Lever window"
                )
            if self.allow_real_followup_send:
                raise ValueError(
                    "Real follow-up sending must remain disabled during the ephemeral Lever window"
                )
            self.allow_real_application_submit = True
            self.lever_supervised_pilot_enabled = True

        sensitive_runtime = any(
            (
                self.is_production,
                self.allow_real_application_submit,
                self.allow_real_followup_send,
                self.greenhouse_supervised_pilot_enabled,
                self.lever_supervised_pilot_enabled,
            )
        )
        if sensitive_runtime and self.uses_placeholder_secret:
            raise ValueError(
                "SECRET_KEY must be a non-placeholder value of at least 32 UTF-8 bytes "
                "for production, real-submission, or outbound-communication operation"
            )

        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
