"""Operational policies for scheduled and autonomous JobTomatik execution."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

from sqlalchemy import func

from app.config import get_settings
from app.models.application import Application, ManualReviewReason, ManualReviewTask
from app.models.job import Job
from app.services.operations_settings import get_operations_settings


@dataclass(frozen=True)
class AutomationDecision:
    allowed: bool
    code: str
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _bounded_hour(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(23, max(0, parsed))


def _positive_int(value: Any, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


def disabled_platforms(value: str | Iterable[str] | None = None) -> set[str]:
    if value is None:
        value = get_operations_settings().disabled_platforms
    items = value.split(",") if isinstance(value, str) else value
    return {str(item).strip().lower() for item in items if str(item).strip()}


def platform_key_for_url(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    if "greenhouse.io" in host:
        return "greenhouse"
    if host.endswith("lever.co") or ".lever.co" in host:
        return "lever"
    if host.endswith("ashbyhq.com") or ".ashbyhq.com" in host:
        return "ashby"
    if host.endswith("smartrecruiters.com") or ".smartrecruiters.com" in host:
        return "smartrecruiters"
    if host.endswith("myworkdayjobs.com") or ".myworkdayjobs.com" in host:
        return "workday"
    return "generic"


def is_quiet_hour(now: datetime, start_hour: int, end_hour: int) -> bool:
    start = _bounded_hour(start_hour, 0)
    end = _bounded_hour(end_hour, 0)
    if start == end:
        return False
    if start < end:
        return start <= now.hour < end
    return now.hour >= start or now.hour < end


def _period_counts(db, user_id: int, now: datetime) -> tuple[int, int]:
    # Caps are rolling operating windows. Calendar-day or calendar-week boundaries
    # would allow a burst immediately after midnight or the start of a new week.
    day_start = now - timedelta(days=1)
    week_start = now - timedelta(days=7)
    daily = (
        db.query(func.count(Application.id))
        .filter(Application.user_id == user_id, Application.created_at >= day_start)
        .scalar()
        or 0
    )
    weekly = (
        db.query(func.count(Application.id))
        .filter(Application.user_id == user_id, Application.created_at >= week_start)
        .scalar()
        or 0
    )
    return int(daily), int(weekly)


def _failure_incidents(
    db,
    user_id: int,
    now: datetime,
    lookback_minutes: int,
) -> List[Dict[str, Any]]:
    cutoff = now - timedelta(minutes=lookback_minutes)
    blocking_reasons = {
        ManualReviewReason.automation_error.value,
        ManualReviewReason.validation_error.value,
        ManualReviewReason.step_navigation_failed.value,
        ManualReviewReason.submission_confirmation_uncertain.value,
    }
    rows = (
        db.query(
            ManualReviewTask.created_at,
            ManualReviewTask.reason_code,
            Application.id,
            Application.application_target_url,
            Job.url,
        )
        .join(Application, ManualReviewTask.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .filter(
            Application.user_id == user_id,
            ManualReviewTask.reason_code.in_(blocking_reasons),
            ManualReviewTask.created_at >= cutoff,
        )
        .order_by(ManualReviewTask.created_at.desc())
        .all()
    )
    incidents: List[Dict[str, Any]] = []
    for created_at, reason_code, application_id, target_url, job_url in rows:
        if created_at is None:
            continue
        url = str(target_url or job_url or "")
        incidents.append({
            "created_at": created_at,
            "reason_code": str(reason_code),
            "application_id": int(application_id),
            "platform": platform_key_for_url(url),
        })
    return incidents


def _circuit_breaker_state(
    db,
    user_id: int,
    now: datetime,
    *,
    threshold: int,
    failure_window_minutes: int,
    breaker_minutes: int,
    platform: str | None = None,
) -> Dict[str, Any] | None:
    incidents = _failure_incidents(db, user_id, now, breaker_minutes)
    if platform:
        incidents = [item for item in incidents if item["platform"] == platform]
    if len(incidents) < threshold:
        return None

    window = timedelta(minutes=failure_window_minutes)
    breaker = timedelta(minutes=breaker_minutes)
    for index in range(0, len(incidents) - threshold + 1):
        cluster = incidents[index : index + threshold]
        newest = cluster[0]["created_at"]
        oldest = cluster[-1]["created_at"]
        if newest - oldest <= window and now < newest + breaker:
            reason_counts = Counter(item["reason_code"] for item in incidents)
            return {
                "scope": "platform" if platform else "user",
                "platform": platform,
                "failure_count": len(incidents),
                "threshold": threshold,
                "failure_window_minutes": failure_window_minutes,
                "breaker_minutes": breaker_minutes,
                "tripped_at": newest.isoformat(),
                "retry_after": (newest + breaker).isoformat(),
                "reason_counts": dict(sorted(reason_counts.items())),
                "application_ids": sorted({item["application_id"] for item in incidents}),
                "operator_reason_code": (
                    "platform_failure_cluster" if platform else "user_failure_cluster"
                ),
            }
    return None


def evaluate_circuit_breaker_policy(
    db,
    user_id: int,
    *,
    url: str | None = None,
    now: datetime | None = None,
) -> AutomationDecision:
    operations = get_operations_settings()
    current = now or datetime.utcnow()
    platform = platform_key_for_url(url or "") if url else None

    if platform:
        platform_state = _circuit_breaker_state(
            db,
            user_id,
            current,
            threshold=operations.failure_threshold,
            failure_window_minutes=operations.failure_window_minutes,
            breaker_minutes=operations.circuit_breaker_minutes,
            platform=platform,
        )
        if platform_state:
            return AutomationDecision(
                False,
                "platform_circuit_breaker_open",
                f"Automation is paused for {platform} after clustered operational failures.",
                platform_state,
            )

    global_state = _circuit_breaker_state(
        db,
        user_id,
        current,
        threshold=operations.failure_threshold,
        failure_window_minutes=operations.failure_window_minutes,
        breaker_minutes=operations.circuit_breaker_minutes,
    )
    if global_state:
        return AutomationDecision(
            False,
            "circuit_breaker_open",
            "Automation is paused after clustered operational failures.",
            global_state,
        )

    return AutomationDecision(
        True,
        "circuit_breaker_closed",
        "No active clustered-failure circuit breaker applies.",
        {"platform": platform},
    )


def evaluate_platform_policy(url: str) -> AutomationDecision:
    operations = get_operations_settings()
    platform = platform_key_for_url(url)
    if operations.global_kill_switch:
        return AutomationDecision(
            False,
            "global_kill_switch_active",
            "All automated execution is stopped by the emergency kill switch.",
            {"platform": platform, "operator_reason_code": "emergency_stop"},
        )
    disabled = disabled_platforms()
    if platform in disabled or "all" in disabled:
        return AutomationDecision(
            False,
            "platform_disabled",
            f"Scheduled automation is not enabled for platform in the current profile: {platform}",
            {
                "platform": platform,
                "disabled_platforms": sorted(disabled),
                "operator_reason_code": "platform_kill_switch",
            },
        )
    return AutomationDecision(True, "platform_allowed", "Platform is enabled", {"platform": platform})


def evaluate_autopilot_policy(db, user, now: datetime | None = None) -> AutomationDecision:
    operations = get_operations_settings()
    now = now or datetime.utcnow()
    user_settings = dict(user.automation_settings or {})

    if operations.global_kill_switch:
        return AutomationDecision(
            False,
            "global_kill_switch_active",
            "All automated execution is stopped by the emergency kill switch.",
            {"operator_reason_code": "emergency_stop"},
        )
    if not operations.autopilot_enabled:
        return AutomationDecision(
            False,
            "global_autopilot_disabled",
            "Autonomous scheduling is not enabled in the current operations profile.",
        )

    start_hour = _bounded_hour(
        user_settings.get("quiet_hours_start_utc"), operations.quiet_hours_start_utc
    )
    end_hour = _bounded_hour(
        user_settings.get("quiet_hours_end_utc"), operations.quiet_hours_end_utc
    )
    if is_quiet_hour(now, start_hour, end_hour):
        return AutomationDecision(
            False,
            "quiet_hours",
            "Scheduled automation is paused during configured UTC quiet hours.",
            {"start_hour_utc": start_hour, "end_hour_utc": end_hour, "current_hour_utc": now.hour},
        )

    requested_daily = _positive_int(
        user_settings.get("auto_apply_daily_limit"), operations.default_daily_cap
    )
    requested_weekly = _positive_int(
        user_settings.get("auto_apply_weekly_limit"), operations.default_weekly_cap
    )
    effective_daily = min(operations.default_daily_cap, requested_daily)
    effective_weekly = min(operations.default_weekly_cap, requested_weekly)
    daily_count, weekly_count = _period_counts(db, user.id, now)
    remaining_daily = max(0, effective_daily - daily_count)
    remaining_weekly = max(0, effective_weekly - weekly_count)
    if remaining_daily == 0 or remaining_weekly == 0:
        return AutomationDecision(
            False,
            "application_cap_reached",
            "Scheduled application creation is paused because a configured cap was reached.",
            {
                "daily_count": daily_count,
                "daily_cap": effective_daily,
                "weekly_count": weekly_count,
                "weekly_cap": effective_weekly,
                "remaining_daily": remaining_daily,
                "remaining_weekly": remaining_weekly,
            },
        )

    circuit = evaluate_circuit_breaker_policy(db, user.id, now=now)
    if not circuit.allowed:
        return circuit

    return AutomationDecision(
        True,
        "autopilot_allowed",
        "Autonomous scheduling is within the configured operating limits.",
        {
            "daily_count": daily_count,
            "daily_cap": effective_daily,
            "weekly_count": weekly_count,
            "weekly_cap": effective_weekly,
            "remaining_daily": remaining_daily,
            "remaining_weekly": remaining_weekly,
            "quiet_hours_start_utc": start_hour,
            "quiet_hours_end_utc": end_hour,
        },
    )


def operations_readiness_manifest() -> Dict[str, Any]:
    core = get_settings()
    operations = get_operations_settings()
    return {
        "version": "1.1.0",
        "global_kill_switch": operations.global_kill_switch,
        "autopilot_enabled": operations.autopilot_enabled,
        "real_submission_enabled": core.allow_real_application_submit,
        "resumable_handoffs_enabled": core.enable_resumable_handoffs,
        "defaults": {
            "daily_cap": operations.default_daily_cap,
            "weekly_cap": operations.default_weekly_cap,
            "quiet_hours_utc": [operations.quiet_hours_start_utc, operations.quiet_hours_end_utc],
            "failure_threshold": operations.failure_threshold,
            "failure_window_minutes": operations.failure_window_minutes,
            "circuit_breaker_minutes": operations.circuit_breaker_minutes,
        },
        "disabled_platforms": sorted(disabled_platforms()),
        "invariants": {
            "global_kill_switch_defaults_inactive": operations.global_kill_switch is False,
            "autopilot_defaults_off": operations.autopilot_enabled is False,
            "real_submission_defaults_off": core.allow_real_application_submit is False,
            "resumable_handoffs_default_off": core.enable_resumable_handoffs is False,
            "user_auto_search_requires_explicit_opt_in": True,
            "user_auto_apply_requires_explicit_opt_in": True,
            "quiet_hours_enforced_before_search_or_apply": True,
            "daily_and_weekly_caps_enforced_before_application_creation": True,
            "repeated_failures_open_circuit_breaker": True,
            "platform_failure_clusters_are_isolated": True,
            "disabled_platforms_are_skipped": True,
            "job_not_marked_applied_until_submission_evidence": True,
        },
    }
