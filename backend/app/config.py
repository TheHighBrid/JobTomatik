import os
import secrets
import sys
from functools import lru_cache
from typing import List, Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.services.operator_assisted_context import operator_final_action_active


DEFAULT_SECRET_KEY = secrets.token_urlsafe(48)
PLACEHOLDER_SECRET_MARKERS = (
    "change-me",
    "replace-with",
    "supersecretkey",
    "development-secret",
)
SUPERVISED_SUBMISSION_SERVICE_MODULE = "app.services.supervised_submission"


def require_persistent_secret(secret: str, purpose: str) -> str:
    """Reject the process-only fallback at durable cryptographic boundaries.

    Explicit legacy keys remain readable for migration. Sensitive operation still
    requires the stronger placeholder/length validation in Settings.
    """
    if not secret.strip() or secret == DEFAULT_SECRET_KEY:
        raise ValueError(f"Configure a stable secret before {purpose}")
    return secret


def _supervised_submission_service_on_stack() -> bool:
    """Return true only while the exact supervised submission service is executing."""

    try:
        frame = sys._getframe(2)
    except (AttributeError, ValueError):
        return False
    for _ in range(20):
        if frame is None:
            break
        if str(frame.f_globals.get("__name__") or "") == SUPERVISED_SUBMISSION_SERVICE_MODULE:
            return True
        frame = frame.f_back
    return False


def _operator_assisted_final_action_on_stack() -> bool:
    """Return true only inside the explicit retained final-action context."""
    return operator_final_action_active()


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
    # Runtime provenance and retained evidence are independent trust inputs. A
    # signed manifest cannot nominate either its own revision or its own evidence.
    autonomy_release_commit: str = ""
    # Immutable release metadata is deployed separately from application code.
    # Files are addressed as <root>/<attested-sha>/<adapter>.json.
    autonomy_release_manifest_dir: str = ""
    autonomy_fixture_artifact: str = ""
    autonomy_evidence_artifact: str = ""
    autonomy_policy_artifact: str = ""
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
    # External CDP is supported for explicit desktop/local modes. The managed
    # Android application route requires native Android Chrome over a loopback
    # ADB-forwarded CDP endpoint and never substitutes Termux Chromium.
    application_browser_cdp_endpoint: str = ""
    # auto preserves desktop behavior; Android-managed execution requires native
    # Chrome. A missing/unavailable endpoint must never launch a different browser.
    application_browser_provider: Literal["auto", "native_chrome", "external_cdp", "local"] = "auto"
    # Keep target resolution nonblocking for headless and solo-worker deployments.
    # A positive value is an explicit opt-in that occupies the current worker task.
    application_target_human_wait_seconds: int = Field(default=0, ge=0, le=3600)

    # Runtime-affinity and retained handoff paths must be loadable from backend/.env
    # because Android-managed API/worker processes intentionally sanitize shell env.
    jobtomatik_browser_node_id: str = ""
    handoff_storage_dir: str = "handoff_sessions"

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

    def __getattribute__(self, name: str):
        """Resolve operator-controlled submission gates and temporary Lever leases.

        Explicit Android-managed values for ``ALLOW_REAL_APPLICATION_SUBMIT`` and
        ``LEVER_SUPERVISED_PILOT_ENABLED`` are authoritative when the operator has
        intentionally enabled them. When the Lever pilot is not persistently enabled,
        the existing process-bound lease may still project the flag true only inside
        the exact supervised API/worker scopes.

        The documented Greenhouse supervised pilot remains configuration-driven.
        Non-Android runtimes preserve their existing explicit configuration behavior.
        """

        value = super().__getattribute__(name)
        if name not in {"allow_real_application_submit", "lever_supervised_pilot_enabled"}:
            return value

        runtime_mode = str(os.environ.get("JOBTOMATIK_RUNTIME_MODE") or "")
        runtime_role = str(os.environ.get("JOBTOMATIK_RUNTIME_ROLE") or "")

        if runtime_mode != "android_managed":
            return value

        # Explicit operator-controlled execution flags are authoritative.
        if value:
            return True

        # The retained operator-assisted lane deliberately requires the persisted
        # global + Lever pilot switches to stay OFF. Suppress temporary lease
        # projection only while an explicit final-action gate scope is active.
        if _operator_assisted_final_action_on_stack():
            return value

        configured_greenhouse = bool(
            super().__getattribute__("greenhouse_supervised_pilot_enabled")
        )
        configured_lever = bool(
            super().__getattribute__("lever_supervised_pilot_enabled")
        )

        if (
            name == "allow_real_application_submit"
            and configured_greenhouse
            and not configured_lever
        ):
            return value

        # If the Lever pilot is not explicitly enabled, preserve the existing
        # process-bound supervised lease behavior as a temporary authorization path.
        value = False
        try:
            from app.services.supervised_runtime_mode import (
                lever_supervised_runtime_lease_active,
            )

            if runtime_role == "api":
                if (
                    _supervised_submission_service_on_stack()
                    and lever_supervised_runtime_lease_active(required_role="api")
                ):
                    return True
                return value

            if runtime_role == "worker":
                from app.services.supervised_runtime import current_supervised_target

                target = dict(current_supervised_target() or {})
                if (
                    str(target.get("platform") or "").strip().lower() == "lever"
                    and lever_supervised_runtime_lease_active(required_role="worker")
                ):
                    return True
        except Exception:
            return value
        return value

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
            or self.secret_key == DEFAULT_SECRET_KEY
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
