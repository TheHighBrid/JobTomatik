"""Runtime adapter and job-data integration for the unattended policy gate."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, time
from typing import Any, Dict, Iterable

from sqlalchemy import func

from app.config import get_settings
from app.models.application import Application
from app.models.job import Job
from app.services.ats_manifest import ats_certification_manifest
from app.services.ats_maturity import AdapterMaturity, normalize_adapter_maturity
from app.services.operations_policy import (
    AutomationDecision,
    disabled_platforms,
    evaluate_autopilot_policy,
    platform_key_for_url,
)
from app.services.operations_settings import get_operations_settings
from app.services.policy_gate import JobContext, OperationCounters, PolicyConfig, PolicyGate


KNOWN_PLATFORMS = {
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workday",
    "generic",
}
REQUIRED_AUTONOMOUS_MATURITY = AdapterMaturity.CERTIFIED_AUTONOMOUS.value
REQUIRED_SCHEDULER_POLICY_VERSION = "bounded-autonomy-v1"
SHADOW_DRY_RUN_ALLOWED_MATURITIES = frozenset(
    {
        AdapterMaturity.DRY_RUN.value,
        AdapterMaturity.HUMAN_REVIEWED_SUBMIT.value,
    }
)
_SHADOW_DRY_RUN_POLICY_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "jobtomatik_shadow_dry_run_policy_context",
    default=None,
)


@contextmanager
def shadow_dry_run_policy_context(*, shadow_session_id: int, dry_run: bool):
    """Scope the narrow Phase 11 maturity exception to one synchronous call tree.

    This context is not authorization by itself. ``evaluate_unattended_job_policy``
    still requires real submission to be disabled and reruns every policy check after
    relaxing only the canonical maturity requirement. The applications worker also
    independently proves the persisted shadow session and application correlation.
    """

    token = _SHADOW_DRY_RUN_POLICY_CONTEXT.set(
        {
            "shadow_session_id": int(shadow_session_id),
            "dry_run": dry_run is True,
        }
    )
    try:
        yield
    finally:
        _SHADOW_DRY_RUN_POLICY_CONTEXT.reset(token)


def _values(value: str | Iterable[str] | None) -> set[str]:
    if not value:
        return set()
    items = value.split(",") if isinstance(value, str) else value
    return {str(item).strip().lower() for item in items if str(item).strip()}


def _optional_values(value: Any) -> set[str] | None:
    parsed = _values(value)
    return parsed or None


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "required"}:
            return True
        if normalized in {"0", "false", "no", "not required"}:
            return False
    return None


def live_platform_maturities() -> Dict[str, str | None]:
    """Read canonical runtime maturity every time and fail closed if absent.

    Descriptive ``certification_level`` text is deliberately ignored. A missing,
    malformed, or unknown canonical maturity remains ``None`` and cannot pass
    the unattended policy gate.
    """

    try:
        adapters = {
            str(item.get("name") or "").lower(): item
            for item in ats_certification_manifest().get("adapters", [])
        }
    except Exception:
        adapters = {}

    result: Dict[str, str | None] = {}
    for platform in sorted(KNOWN_PLATFORMS):
        manifest = adapters.get(platform) or {}
        maturity = normalize_adapter_maturity(manifest.get("maturity"))
        result[platform] = maturity.value if maturity else None
    return result


def _job_context(job: Job) -> JobContext:
    raw = dict(job.raw_data or {})
    target_url = raw.get("selected_apply_url") or job.url or ""

    language_value = (
        raw.get("language") or raw.get("job_language") or raw.get("languages")
    )
    if isinstance(language_value, (list, tuple, set)):
        language_value = next(
            (str(item) for item in language_value if str(item).strip()), None
        )

    sponsorship = None
    for key in (
        "requires_sponsorship",
        "sponsorship_required",
        "visa_sponsorship_required",
    ):
        if key in raw:
            sponsorship = _optional_bool(raw.get(key))
            break

    employer_name = str(job.company or "").strip()
    return JobContext(
        adapter_platform=platform_key_for_url(target_url),
        employer_id=employer_name.lower(),
        employer_name=employer_name,
        job_id=str(job.id or job.external_id or ""),
        location=str(job.location).strip().lower() if job.location else None,
        salary_min=int(job.salary_min) if job.salary_min is not None else None,
        seniority=str(job.seniority).strip().lower() if job.seniority else None,
        language=(
            str(language_value).strip().lower() if language_value else None
        ),
        requires_sponsorship=sponsorship,
        source=str(job.source or raw.get("source") or "unknown").strip().lower(),
    )


def _employer_daily_count(
    db,
    user_id: int,
    employer_name: str,
    now: datetime,
) -> int:
    day_start = datetime(now.year, now.month, now.day)
    count = (
        db.query(func.count(Application.id))
        .join(Job, Application.job_id == Job.id)
        .filter(
            Application.user_id == user_id,
            Application.created_at >= day_start,
            func.lower(Job.company) == employer_name.strip().lower(),
        )
        .scalar()
        or 0
    )
    return int(count)


def _platform_enabled(user_settings: Dict[str, Any], platform: str) -> bool:
    """Per-platform switch is explicit opt-in and therefore closed by default."""
    enabled = _values(user_settings.get("autopilot_enabled_platforms"))
    disabled = disabled_platforms()
    return (
        (platform in enabled or "all" in enabled)
        and platform not in disabled
        and "all" not in disabled
    )


def evaluate_unattended_job_policy(
    db,
    user,
    job: Job,
    now: datetime | None = None,
) -> AutomationDecision:
    """Gate a scheduled job before record creation and again before the worker.

    The only maturity exception is a scoped Phase 11 shadow dry run. It can relax
    ``certified_autonomous`` to an already evidence-backed dry-run/human-reviewed
    maturity only while real submission is disabled. All other policy checks are
    rerun unchanged before the exception can return ALLOW.
    """
    now = now or datetime.utcnow()
    user_settings = dict(user.automation_settings or {})

    # Historical auto-search/auto-apply values predate the bounded-autonomy
    # contract and cannot authorize any unattended entry point. This check lives
    # at the shared worker policy chokepoint so scheduler and non-scheduler callers
    # fail closed in the same way.
    current_policy_version = str(user_settings.get("scheduler_policy_version") or "")
    if current_policy_version != REQUIRED_SCHEDULER_POLICY_VERSION:
        return AutomationDecision(
            False,
            "scheduler_policy_upgrade_required",
            "Explicit Phase 8 bounded scheduler policy activation is required.",
            {
                "current_scheduler_policy_version": current_policy_version or None,
                "required_scheduler_policy_version": REQUIRED_SCHEDULER_POLICY_VERSION,
                "job_id": str(job.id or job.external_id or ""),
            },
        )

    user_decision = evaluate_autopilot_policy(db, user, now)
    if not user_decision.allowed:
        return user_decision

    operations = get_operations_settings()
    core = get_settings()
    ctx = _job_context(job)
    maturities = live_platform_maturities()
    canonical_maturity = maturities.get(ctx.adapter_platform)
    shadow_context = _SHADOW_DRY_RUN_POLICY_CONTEXT.get() or {}
    shadow_session_id = shadow_context.get("shadow_session_id")
    shadow_dry_run = shadow_context.get("dry_run") is True
    real_submission_enabled = bool(core.allow_real_application_submit)

    daily_count = int(user_decision.metadata.get("daily_count", 0))
    weekly_count = int(user_decision.metadata.get("weekly_count", 0))
    employer_count = _employer_daily_count(
        db, user.id, ctx.employer_name, now
    )

    try:
        per_employer_cap = max(
            1, int(user_settings.get("auto_apply_daily_per_employer_limit", 1))
        )
    except (TypeError, ValueError):
        per_employer_cap = 1

    try:
        min_salary = int(user_settings.get("autopilot_min_salary", 0)) or None
    except (TypeError, ValueError):
        min_salary = None

    start_hour = max(
        0,
        min(
            23,
            int(
                user_settings.get(
                    "quiet_hours_start_utc",
                    operations.quiet_hours_start_utc,
                )
            ),
        ),
    )
    end_hour = max(
        0,
        min(
            23,
            int(
                user_settings.get(
                    "quiet_hours_end_utc",
                    operations.quiet_hours_end_utc,
                )
            ),
        ),
    )

    config = PolicyConfig(
        global_autonomy_enabled=operations.autopilot_enabled,
        platform_enabled={
            ctx.adapter_platform: _platform_enabled(
                user_settings, ctx.adapter_platform
            )
        },
        platform_maturity={
            ctx.adapter_platform: canonical_maturity
        },
        required_platform_maturity=REQUIRED_AUTONOMOUS_MATURITY,
        daily_cap_global=int(user_decision.metadata.get("daily_cap", 0)),
        weekly_cap_global=int(user_decision.metadata.get("weekly_cap", 0)),
        daily_cap_per_employer=per_employer_cap,
        quiet_hours_start=time(start_hour),
        quiet_hours_end=time(end_hour),
        employer_allow_list=_optional_values(
            user_settings.get("autopilot_employer_allow_list")
        ),
        employer_exclude_list=_values(
            user_settings.get("autopilot_employer_exclude_list")
        ),
        allowed_locations=_optional_values(
            user_settings.get("autopilot_allowed_locations")
        ),
        min_salary=min_salary,
        allowed_seniority=_optional_values(
            user_settings.get("autopilot_allowed_seniority")
        ),
        allowed_languages=_optional_values(
            user_settings.get("autopilot_allowed_languages")
        ),
        require_sponsorship_match=True,
        require_known_job_attributes=True,
        circuit_breaker_failure_threshold=operations.failure_threshold,
    )
    counters = OperationCounters(
        submissions_today_global=daily_count,
        submissions_this_week_global=weekly_count,
        submissions_today_for_employer={ctx.employer_id: employer_count},
    )
    result = PolicyGate(config, now_fn=lambda: now).evaluate(ctx, counters)
    shadow_exception_applied = False

    if (
        result.reason_code == "platform_not_certified"
        and shadow_session_id is not None
        and shadow_dry_run
        and not real_submission_enabled
        and canonical_maturity in SHADOW_DRY_RUN_ALLOWED_MATURITIES
    ):
        # Rerun the complete gate with only the maturity equality relaxed to the
        # already observed canonical maturity. Circuit breakers, quiet hours,
        # employer/cap constraints, and verified job attributes still must pass.
        shadow_config = replace(
            config,
            required_platform_maturity=str(canonical_maturity),
        )
        shadow_result = PolicyGate(shadow_config, now_fn=lambda: now).evaluate(
            ctx,
            counters,
        )
        if shadow_result.allowed:
            result = shadow_result
            shadow_exception_applied = True
        else:
            result = shadow_result

    metadata = {
        **user_decision.metadata,
        "job_id": ctx.job_id,
        "platform": ctx.adapter_platform,
        "platform_maturity": canonical_maturity,
        "required_platform_maturity": REQUIRED_AUTONOMOUS_MATURITY,
        "scheduler_policy_version": current_policy_version,
        "policy_detail": result.detail,
        "shadow_session_id": shadow_session_id,
        "shadow_dry_run": shadow_dry_run,
        "real_submission_enabled": real_submission_enabled,
        "shadow_dry_run_maturity_exception": shadow_exception_applied,
    }
    if shadow_exception_applied:
        return AutomationDecision(
            True,
            "shadow_dry_run_maturity_exception",
            "All unattended policy checks passed under the Phase 11 dry-run-only maturity exception.",
            metadata,
        )
    return AutomationDecision(
        result.allowed,
        result.reason_code,
        result.detail,
        metadata,
    )
