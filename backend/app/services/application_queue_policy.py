"""Day 30 policy-bounded application queue controls and durable audit evidence.

This layer intentionally composes with the existing unattended policy rather than
replacing it. The existing gate remains authoritative for global/user caps, quiet
hours, circuit breakers, employer lists, salary, location, seniority, language,
and adapter maturity. Day 30 adds the missing role, workplace-mode, work-
authorization, and per-platform-cap controls, then records every evaluated job
policy decision as a durable AgentRun audit record.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from app.models.application import Application
from app.models.intelligence import AgentRun
from app.models.job import Job, JobType
from app.services.operations_policy import AutomationDecision, platform_key_for_url


DAY30_POLICY_VERSION = "policy-bounded-queue-v1"
ALLOWED_WORKPLACE_MODES = frozenset({"remote", "hybrid", "onsite"})

_HOLD_CODES = frozenset(
    {
        "global_kill_switch_active",
        "global_autopilot_disabled",
        "quiet_hours",
        "application_cap_reached",
        "daily_cap_reached",
        "weekly_cap_reached",
        "employer_daily_cap_reached",
        "platform_daily_cap_reached",
        "platform_circuit_breaker_open",
        "circuit_breaker_open",
        "circuit_open",
        "circuit_threshold_reached",
        "platform_not_certified",
        "platform_kill_switch_off",
        "scheduler_policy_upgrade_required",
        "policy_configuration_incomplete",
        "job_attributes_unknown",
        "workplace_mode_unknown",
        "work_authorization_country_unknown",
    }
)

_COUNTRY_ALIASES = {
    "ca": "canada",
    "can": "canada",
    "canada": "canada",
    "us": "united states",
    "usa": "united states",
    "u.s.": "united states",
    "u.s.a.": "united states",
    "united states": "united states",
    "united states of america": "united states",
    "uk": "united kingdom",
    "gb": "united kingdom",
    "gbr": "united kingdom",
    "united kingdom": "united kingdom",
}


def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = [value]
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        normalized = " ".join(str(item or "").strip().lower().split())
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _country(value: Any) -> str | None:
    normalized = " ".join(str(value or "").strip().lower().split())
    if not normalized:
        return None
    return _COUNTRY_ALIASES.get(normalized, normalized)


def workplace_mode(job: Job) -> str | None:
    raw = dict(job.raw_data or {})
    for key in ("workplace_mode", "workplace_type", "remote_status", "location_type"):
        value = " ".join(str(raw.get(key) or "").strip().lower().split())
        if not value:
            continue
        if value in ALLOWED_WORKPLACE_MODES:
            return value
        if value in {"on-site", "on site", "office", "in office", "in-office"}:
            return "onsite"
        if value in {"partially remote", "flexible", "mixed"}:
            return "hybrid"
        if value in {"fully remote", "remote-first", "remote first"}:
            return "remote"
    if raw.get("remote") is True:
        return "remote"
    job_type = getattr(job.job_type, "value", job.job_type)
    if str(job_type or "").strip().lower() == JobType.remote.value:
        return "remote"
    location = " ".join(str(job.location or "").strip().lower().split())
    if location in {"remote", "remote - canada", "remote - us", "remote - usa"}:
        return "remote"
    return None


def work_authorization_country(job: Job) -> str | None:
    raw = dict(job.raw_data or {})
    for key in (
        "work_authorization_country",
        "employment_country",
        "country",
        "country_code",
    ):
        parsed = _country(raw.get(key))
        if parsed:
            return parsed
    return None


def _role_allowed(title: str, allowed_roles: list[str]) -> bool:
    normalized_title = " ".join(str(title or "").strip().lower().split())
    if not normalized_title:
        return False
    return any(role == normalized_title or role in normalized_title for role in allowed_roles)


def _platform_daily_count(db, user_id: int, platform: str, now: datetime) -> int:
    cutoff = now - timedelta(days=1)
    rows = (
        db.query(Application, Job)
        .join(Job, Application.job_id == Job.id)
        .filter(
            Application.user_id == int(user_id),
            Application.created_at >= cutoff,
        )
        .all()
    )
    count = 0
    for application, job in rows:
        url = str(application.application_target_url or job.url or "")
        if platform_key_for_url(url) == platform:
            count += 1
    return count


def _platform_limits(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, raw_limit in value.items():
        platform = str(key or "").strip().lower()
        if not platform:
            continue
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            continue
        if limit > 0:
            result[platform] = limit
    return result


def classify_disposition(decision: AutomationDecision) -> str:
    if decision.allowed:
        return "accepted"
    if decision.code in _HOLD_CODES or decision.code.endswith("_unknown"):
        return "held"
    return "rejected"


def _audit_decision(
    db,
    user,
    job: Job,
    decision: AutomationDecision,
    *,
    stage: str,
    now: datetime,
) -> int | None:
    payload = decision.to_dict()
    run = AgentRun(
        user_id=int(user.id),
        objective="Day 30 policy-bounded application queue decision",
        status="completed",
        autonomy_level="policy_gate",
        risk_level="high",
        requires_approval=not decision.allowed,
        plan=["evaluate_job_policy", "record_explanation"],
        run_context={
            "policy_version": DAY30_POLICY_VERSION,
            "stage": stage,
            "job_id": int(job.id) if job.id is not None else None,
            "external_id": str(job.external_id or "") or None,
        },
        result={
            "disposition": classify_disposition(decision),
            "allowed": bool(decision.allowed),
            "code": decision.code,
            "reason": decision.reason,
            "metadata": payload.get("metadata") or {},
        },
        started_at=now,
        completed_at=now,
    )
    db.add(run)
    try:
        db.flush()
    except Exception:
        return None
    return int(run.id) if run.id is not None else None


def evaluate_day30_constraints(
    db,
    user,
    job: Job,
    *,
    now: datetime,
    platform: str,
) -> AutomationDecision:
    settings = dict(user.automation_settings or {})
    allowed_roles = _values(settings.get("autopilot_allowed_roles"))
    allowed_workplace_modes = _values(settings.get("autopilot_allowed_workplace_modes"))
    authorized_countries = {
        parsed
        for parsed in (_country(item) for item in _values(settings.get("autopilot_authorized_countries")))
        if parsed
    }
    platform_limits = _platform_limits(settings.get("autopilot_daily_platform_limits"))
    allow_sponsorship = bool(settings.get("autopilot_allow_sponsorship_required", False))

    missing_policy: list[str] = []
    if not allowed_roles:
        missing_policy.append("autopilot_allowed_roles")
    if not allowed_workplace_modes:
        missing_policy.append("autopilot_allowed_workplace_modes")
    if not authorized_countries:
        missing_policy.append("autopilot_authorized_countries")
    if platform not in platform_limits:
        missing_policy.append(f"autopilot_daily_platform_limits.{platform}")
    if missing_policy:
        return AutomationDecision(
            False,
            "policy_configuration_incomplete",
            "Unattended queueing requires explicit Day 30 role, workplace, authorization, and platform-cap policy.",
            {
                "policy_version": DAY30_POLICY_VERSION,
                "missing_policy_fields": missing_policy,
                "platform": platform,
            },
        )

    if not _role_allowed(str(job.title or ""), allowed_roles):
        return AutomationDecision(
            False,
            "role_not_allowed",
            f"Role {job.title!r} does not match the unattended role allowlist.",
            {"allowed_roles": allowed_roles, "platform": platform},
        )

    mode = workplace_mode(job)
    if mode is None:
        return AutomationDecision(
            False,
            "workplace_mode_unknown",
            "Unattended queueing requires an explicit remote, hybrid, or onsite workplace mode.",
            {"allowed_workplace_modes": allowed_workplace_modes, "platform": platform},
        )
    if mode not in allowed_workplace_modes:
        return AutomationDecision(
            False,
            "workplace_mode_not_allowed",
            f"Workplace mode {mode!r} is not allowed.",
            {"workplace_mode": mode, "allowed_workplace_modes": allowed_workplace_modes, "platform": platform},
        )

    raw = dict(job.raw_data or {})
    sponsorship = None
    for key in ("requires_sponsorship", "sponsorship_required", "visa_sponsorship_required"):
        if key in raw:
            value = raw.get(key)
            if isinstance(value, bool):
                sponsorship = value
            elif isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"true", "yes", "1", "required"}:
                    sponsorship = True
                elif normalized in {"false", "no", "0", "not required"}:
                    sponsorship = False
            break

    country = work_authorization_country(job)
    if sponsorship is True:
        if not allow_sponsorship:
            return AutomationDecision(
                False,
                "sponsorship_required_not_allowed",
                "This job requires sponsorship and unattended policy does not allow sponsorship-required roles.",
                {"platform": platform, "allow_sponsorship_required": False},
            )
    else:
        if country is None:
            return AutomationDecision(
                False,
                "work_authorization_country_unknown",
                "The job's employment/work-authorization country is unknown.",
                {"authorized_countries": sorted(authorized_countries), "platform": platform},
            )
        if country not in authorized_countries:
            return AutomationDecision(
                False,
                "work_authorization_not_allowed",
                f"Employment country {country!r} is outside the user's unattended authorization policy.",
                {"job_country": country, "authorized_countries": sorted(authorized_countries), "platform": platform},
            )

    platform_limit = int(platform_limits[platform])
    platform_count = _platform_daily_count(db, int(user.id), platform, now)
    if platform_count >= platform_limit:
        return AutomationDecision(
            False,
            "platform_daily_cap_reached",
            f"Daily {platform} application count {platform_count} reached cap {platform_limit}.",
            {
                "platform": platform,
                "platform_daily_count": platform_count,
                "platform_daily_cap": platform_limit,
            },
        )

    return AutomationDecision(
        True,
        "day30_queue_policy_allowed",
        "Role, workplace mode, work authorization, and per-platform cap checks passed.",
        {
            "policy_version": DAY30_POLICY_VERSION,
            "platform": platform,
            "role": str(job.title or ""),
            "workplace_mode": mode,
            "work_authorization_country": country,
            "sponsorship_required": sponsorship,
            "platform_daily_count": platform_count,
            "platform_daily_cap": platform_limit,
        },
    )


def build_policy_evaluator(
    base_evaluator: Callable[..., AutomationDecision],
) -> Callable[..., AutomationDecision]:
    """Wrap the inherited unattended gate without weakening any existing decision."""

    def evaluate(db, user, job: Job, now: datetime | None = None) -> AutomationDecision:
        current = now or datetime.utcnow()
        base = base_evaluator(db, user, job, now=current)
        stage = "worker_or_scheduler"
        if not base.allowed:
            audit_id = _audit_decision(db, user, job, base, stage=stage, now=current)
            if audit_id is not None:
                return AutomationDecision(
                    base.allowed,
                    base.code,
                    base.reason,
                    {**dict(base.metadata or {}), "policy_audit_run_id": audit_id},
                )
            return base

        raw = dict(job.raw_data or {})
        target_url = str(raw.get("selected_apply_url") or job.url or "")
        platform = platform_key_for_url(target_url)
        day30 = evaluate_day30_constraints(db, user, job, now=current, platform=platform)
        merged = AutomationDecision(
            day30.allowed,
            day30.code,
            day30.reason,
            {
                **dict(base.metadata or {}),
                **dict(day30.metadata or {}),
                "inherited_policy_code": base.code,
            },
        )
        audit_id = _audit_decision(db, user, job, merged, stage=stage, now=current)
        if audit_id is not None:
            merged = AutomationDecision(
                merged.allowed,
                merged.code,
                merged.reason,
                {**dict(merged.metadata or {}), "policy_audit_run_id": audit_id},
            )
        return merged

    return evaluate
