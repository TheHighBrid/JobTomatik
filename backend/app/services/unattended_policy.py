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
from app.models.certification import ShadowRunSession
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
SHADOW_QUALIFICATION_CANARY_TARGET = "shadow_qualification_canary"
SHADOW_DRY_RUN_ALLOWED_MATURITIES = frozenset(
    {
        AdapterMaturity.DRY_RUN.value,
        AdapterMaturity.HUMAN_REVIEWED_SUBMIT.value,
        AdapterMaturity.CERTIFIED_AUTONOMOUS.value,
    }
)
_SHADOW_DRY_RUN_POLICY_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "jobtomatik_shadow_dry_run_policy_context",
    default=None,
)


@contextmanager
def shadow_dry_run_policy_context(
    *,
    shadow_session_id: int,
    dry_run: bool,
    application_id: int | None = None,
):
    """Scope the narrow Phase 11 exception to one synchronous call tree.

    The context is never submission authority. The scheduler establishes it only for
    an explicit Phase 11 shadow cycle, while the applications worker independently
    derives and validates the same session from durable application evidence. Real
    submission must remain disabled before any shadow relaxation is considered.
    """

    token = _SHADOW_DRY_RUN_POLICY_CONTEXT.set(
        {
            "shadow_session_id": int(shadow_session_id),
            "dry_run": dry_run is True,
            "application_id": (
                int(application_id) if application_id is not None else None
            ),
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
    """Read canonical runtime maturity every time and fail closed if absent."""

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
    *,
    exclude_application_id: int | None = None,
) -> int:
    day_start = datetime(now.year, now.month, now.day)
    query = (
        db.query(func.count(Application.id))
        .join(Job, Application.job_id == Job.id)
        .filter(
            Application.user_id == user_id,
            Application.created_at >= day_start,
            func.lower(Job.company) == employer_name.strip().lower(),
        )
    )
    if exclude_application_id is not None:
        query = query.filter(Application.id != int(exclude_application_id))
    return int(query.scalar() or 0)


def _platform_enabled(user_settings: Dict[str, Any], platform: str) -> bool:
    """Normal live unattended execution requires explicit per-platform opt-in."""
    enabled = _values(user_settings.get("autopilot_enabled_platforms"))
    disabled = disabled_platforms()
    return (
        (platform in enabled or "all" in enabled)
        and platform not in disabled
        and "all" not in disabled
    )


def _shadow_platform_enabled(platform: str) -> bool:
    """An explicit no-submit shadow run is the opt-in; emergency disables still win."""
    disabled = disabled_platforms()
    return platform not in disabled and "all" not in disabled


def _shadow_qualification_probe(db, *, user_id: int, shadow_session_id: Any) -> bool:
    """Prove that a shadow context is the durable non-certifying qualification canary.

    Qualification needs to exercise a real ATS/browser path even when the configured
    public ATS board has no posting that matches the account's normal job-interest
    filters at that instant. The relaxation below is therefore keyed to durable session
    evidence, never a task kwarg or transient caller flag. It cannot apply to a timed
    ``shadow_run_4h`` campaign or to normal unattended execution.
    """

    try:
        session_id = int(shadow_session_id)
    except (TypeError, ValueError):
        return False
    if session_id <= 0:
        return False

    session = (
        db.query(ShadowRunSession)
        .filter(
            ShadowRunSession.id == session_id,
            ShadowRunSession.user_id == int(user_id),
        )
        .first()
    )
    if session is None or session.status != "running":
        return False
    if session.target_evidence_type != SHADOW_QUALIFICATION_CANARY_TARGET:
        return False
    if session.final_submit_allowed is not False:
        return False

    snapshot = dict(session.configuration_snapshot or {})
    invariants = dict(snapshot.get("invariants") or {})
    return bool(
        snapshot.get("qualification_canary") is True
        and snapshot.get("certification_eligible") is False
        and invariants.get("dry_run_required") is True
        and invariants.get("real_submission_must_remain_disabled") is True
        and invariants.get("final_submit_allowed") is False
        and invariants.get("submission_authorized") is False
        and invariants.get("outreach_authorized") is False
        and invariants.get("adapter_maturity_mutated") is False
    )


def evaluate_unattended_job_policy(
    db,
    user,
    job: Job,
    now: datetime | None = None,
) -> AutomationDecision:
    """Gate a scheduled job before record creation and again before browser work.

    Ordinary unattended execution retains the full live contract, including explicit
    platform opt-in, complete consequential job facts, and ``certified_autonomous``
    maturity. A durable Phase 11 shadow call tree may relax only what is necessary to
    exercise a nonconsequential dry-run form before autonomous promotion: canonical
    maturity may be dry-run or better, the shadow start substitutes for the live-submit
    platform opt-in, and missing salary/language/sponsorship facts may remain unknown.

    The non-certifying qualification canary is narrower still: once its durable session
    identity and no-submit invariants are proven, job-interest suitability filters
    (allow-list, location, salary, seniority, and language) are not used to decide which
    configured ATS form may serve as the probe. Caps, quiet hours, circuit breakers,
    global controls, employer exclusions, platform disables, dry-run, and real-submit
    safety remain authoritative. Timed shadow campaigns retain the normal suitability
    filters.
    """
    now = now or datetime.utcnow()
    user_settings = dict(user.automation_settings or {})

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

    operations = get_operations_settings()
    core = get_settings()
    ctx = _job_context(job)
    maturities = live_platform_maturities()
    canonical_maturity = maturities.get(ctx.adapter_platform)
    shadow_context = _SHADOW_DRY_RUN_POLICY_CONTEXT.get() or {}
    shadow_session_id = shadow_context.get("shadow_session_id")
    shadow_dry_run = shadow_context.get("dry_run") is True
    shadow_application_id = shadow_context.get("application_id")
    real_submission_enabled = bool(core.allow_real_application_submit)
    shadow_policy_candidate = bool(
        shadow_session_id is not None
        and shadow_dry_run
        and not real_submission_enabled
    )
    shadow_qualification_probe = bool(
        shadow_policy_candidate
        and _shadow_qualification_probe(
            db,
            user_id=int(user.id),
            shadow_session_id=shadow_session_id,
        )
    )

    user_decision = evaluate_autopilot_policy(
        db,
        user,
        now,
        exclude_application_id=(
            int(shadow_application_id)
            if shadow_policy_candidate and shadow_application_id is not None
            else None
        ),
    )
    if not user_decision.allowed:
        return user_decision

    daily_count = int(user_decision.metadata.get("daily_count", 0))
    weekly_count = int(user_decision.metadata.get("weekly_count", 0))
    employer_count = _employer_daily_count(
        db,
        user.id,
        ctx.employer_name,
        now,
        exclude_application_id=(
            int(shadow_application_id)
            if shadow_policy_candidate and shadow_application_id is not None
            else None
        ),
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
            ctx.adapter_platform: (
                _shadow_platform_enabled(ctx.adapter_platform)
                if shadow_policy_candidate
                else _platform_enabled(user_settings, ctx.adapter_platform)
            )
        },
        platform_maturity={ctx.adapter_platform: canonical_maturity},
        required_platform_maturity=REQUIRED_AUTONOMOUS_MATURITY,
        daily_cap_global=int(user_decision.metadata.get("daily_cap", 0)),
        weekly_cap_global=int(user_decision.metadata.get("weekly_cap", 0)),
        daily_cap_per_employer=per_employer_cap,
        quiet_hours_start=time(start_hour),
        quiet_hours_end=time(end_hour),
        employer_allow_list=(
            None
            if shadow_qualification_probe
            else _optional_values(user_settings.get("autopilot_employer_allow_list"))
        ),
        employer_exclude_list=_values(
            user_settings.get("autopilot_employer_exclude_list")
        ),
        allowed_locations=(
            None
            if shadow_qualification_probe
            else _optional_values(user_settings.get("autopilot_allowed_locations"))
        ),
        min_salary=None if shadow_qualification_probe else min_salary,
        allowed_seniority=(
            None
            if shadow_qualification_probe
            else _optional_values(user_settings.get("autopilot_allowed_seniority"))
        ),
        allowed_languages=(
            None
            if shadow_qualification_probe
            else _optional_values(user_settings.get("autopilot_allowed_languages"))
        ),
        require_sponsorship_match=not shadow_policy_candidate,
        require_known_job_attributes=not shadow_policy_candidate,
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
        and shadow_policy_candidate
        and canonical_maturity in SHADOW_DRY_RUN_ALLOWED_MATURITIES
    ):
        shadow_config = replace(
            config,
            required_platform_maturity=str(canonical_maturity),
        )
        result = PolicyGate(shadow_config, now_fn=lambda: now).evaluate(ctx, counters)
        shadow_exception_applied = result.allowed

    metadata = {
        **user_decision.metadata,
        "job_id": ctx.job_id,
        "platform": ctx.adapter_platform,
        "platform_maturity": canonical_maturity,
        "required_platform_maturity": REQUIRED_AUTONOMOUS_MATURITY,
        "scheduler_policy_version": current_policy_version,
        "policy_detail": result.detail,
        "shadow_session_id": shadow_session_id,
        "shadow_application_id": shadow_application_id,
        "shadow_dry_run": shadow_dry_run,
        "real_submission_enabled": real_submission_enabled,
        "shadow_policy_candidate": shadow_policy_candidate,
        "shadow_qualification_probe": shadow_qualification_probe,
        "shadow_qualification_suitability_filters_bypassed": shadow_qualification_probe,
        "shadow_live_platform_switch_bypassed": shadow_policy_candidate,
        "shadow_unknown_job_attributes_allowed": shadow_policy_candidate,
        "shadow_dry_run_maturity_exception": shadow_exception_applied,
    }
    if shadow_exception_applied:
        return AutomationDecision(
            True,
            "shadow_dry_run_maturity_exception",
            "All policy checks passed under the Phase 11 no-submit dry-run maturity exception.",
            metadata,
        )
    return AutomationDecision(
        result.allowed,
        result.reason_code,
        result.detail,
        metadata,
    )
