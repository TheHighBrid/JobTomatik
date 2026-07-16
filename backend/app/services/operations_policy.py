"""Bounded unattended-operation policies for JobTomatik.

These controls deliberately govern scheduled automation separately from human-reviewed
application work. Live submission remains protected by the existing submission safety gate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List
from urllib.parse import urlparse

from sqlalchemy import func

from app.config import get_settings
from app.models.application import Application, ManualReviewReason, ManualReviewTask


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
        value = get_settings().autopilot_disabled_platforms
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = value
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
    """Return whether ``now`` falls inside a UTC quiet-hours window.

    Equal start and end values disable quiet hours. Wraparound windows such as 22 -> 6
    are supported.
    """

    start = _bounded_hour(start_hour, 0)
    end = _bounded_hour(end_hour, 0)
    if start == end:
        return False
    if start < end:
        return start <= now.hour < end
    return now.hour >= start or now.hour < end


def _period_counts(db, user_id: int, now: datetime) -> tuple[int, int]:
    day_start = datetime(now.year, now.month, now.day)
    week_start = day_start - timedelta(days=day_start.weekday())

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


def _failure_timestamps(db, user_id: int, now: datetime, lookback_minutes: int) -> List[datetime]:
    cutoff = now - timedelta(minutes=lookback_minutes)
    blocking_reasons = {
        ManualReviewReason.automation_error.value,
        ManualReviewReason.validation_error.value,
        ManualReviewReason.step_navigation_failed.value,
        ManualReviewReason.submission_confirmation_uncertain.value,
    }
    rows = (
        db.query(ManualReviewTask.created_at)
        .join(Application, ManualReviewTask.application_id == Application.id)
        .filter(
            Application.user_id == user_id,
            ManualReviewTask.reason_code.in_(blocking_reasons),
            ManualReviewTask.created_at >= cutoff,
        )
        .order_by(ManualReviewTask.created_at.desc())
        .all()
    )
    return [row[0] for row in rows if row[0] is not None]


def _circuit_breaker_state(
    db,
    user_id: int,
    now: datetime,
    *,
    threshold: int,
    failure_window_minutes: int,
    breaker_minutes: int,
) -> Dict[str, Any] | None:
    timestamps = _failure_timestamps(db, user_id, now, breaker_minutes)
    if len(timestamps) < threshold:
        return None

    window = timedelta(minutes=failure_window_minutes)
    breaker = timedelta(minutes=breaker_minutes)
    for index in range(0, len(timestamps) - threshold + 1):
        cluster = timestamps[index : index + threshold]
        newest = cluster[0]
        oldest = cluster[-1]
        if newest - oldest <= window and now < newest + breaker:
            return {
                "failure_count": len(timestamps),
                "threshold": threshold,
                "tripped_at": newest.isoformat(),
                "retry_after": (newest + breaker).isoformat(),
            }
    return None


def evaluate_platform_policy(url: str) -> AutomationDecision:
    platform = platform_key_for_url(url)
    disabled = disabled_platforms()
    if platform in disabled or "all" in disabled:
        return AutomationDecision(
            False,
            "platform_disabled",
            f"Scheduled automation is disabled for platform: {platform}",
            {"platform": platform, "disabled_platforms": sorted(disabled)},
        )
    return AutomationDecision(True, "platform_allowed", "Platform is enabled", {"platform": platform})


def evaluate_autopilot_policy(db, user, now: datetime | None = None) -> AutomationDecision:
    settings = get_settings()
    now = now or datetime.utcnow()
    automation_settings = dict(user.automation_settings or {})

    if not settings.autopilot_enabled:
        return AutomationDecision(
            False,
            "global_autopilot_disabled",
            "Scheduled unattended automation is disabled globally.",
        )

    start_hour = _bounded_hour(
        automation_settings.get("quiet_hours_start_utc"),
        settings.autopilot_quiet_hours_start_utc,
    )
    end_hour = _bounded_hour(
        automation_settings.get("quiet_hours_end_utc"),
        settings.autopilot_quiet_hours_end_utc,
    )
    if is_quiet_hour(now, start_hour, end_hour):
        return AutomationDecision(
            False,
            "quiet_hours",
            "Scheduled automation is paused during configured UTC quiet hours.",
            {"start_hour_utc": start_hour, "end_hour_utc": end_hour, "current_hour_utc": now.hour},
        )

    global_daily = _positive_int(settings.autopilot_default_daily_cap, 5)
    global_weekly = _positive_int(settings.autopilot_default_weekly_cap, 20)
    requested_daily = _positive_int(automation_settings.get("auto_apply_daily_limit"), global_daily)
    requested_weekly = _positive_int(automation_settings.get("auto_apply_weekly_limit"), global_weekly)
    effective_daily = min(global_daily, requested_daily)
    effective_weekly = min(global_weekly, requested_weekly)

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

    threshold = _positive_int(settings.autopilot_failure_threshold, 3)
    failure_window = _positive_int(settings.autopilot_failure_window_minutes, 60)
    breaker_minutes = _positive_int(settings.autopilot_circuit_breaker_minutes, 120)
    circuit = _circuit_breaker_state(
        db,
        user.id,
        now,
        threshold=threshold,
        failure_window_minutes=failure_window,
        breaker_minutes=breaker_minutes,
    )
    if circuit:
        return AutomationDecision(
            False,
            "circuit_breaker_open",
            "Scheduled applications are paused after repeated automation failures.",
            circuit,
        )

    return AutomationDecision(
        True,
        "autopilot_allowed",
        "Scheduled automation is within configured safety limits.",
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
    settings = get_settings()
    return {
        "version": "1.0.0",
        "autopilot_enabled": settings.autopilot_enabled,
        "real_submission_enabled": settings.allow_real_application_submit,
        "defaults": {
            "daily_cap": settings.autopilot_default_daily_cap,
            "weekly_cap": settings.autopilot_default_weekly_cap,
            "quiet_hours_utc": [
                settings.autopilot_quiet_hours_start_utc,
                settings.autopilot_quiet_hours_end_utc,
            ],
            "failure_threshold": settings.autopilot_failure_threshold,
            "failure_window_minutes": settings.autopilot_failure_window_minutes,
            "circuit_breaker_minutes": settings.autopilot_circuit_breaker_minutes,
        },
        "disabled_platforms": sorted(disabled_platforms()),
        "invariants": {
            "autopilot_defaults_off": settings.autopilot_enabled is False,
            "real_submission_defaults_off": settings.allow_real_application_submit is False,
            "user_auto_search_requires_explicit_opt_in": True,
            "user_auto_apply_requires_explicit_opt_in": True,
            "quiet_hours_enforced_before_search_or_apply": True,
            "daily_and_weekly_caps_enforced_before_application_creation": True,
            "repeated_failures_open_circuit_breaker": True,
            "disabled_platforms_are_skipped": True,
            "job_not_marked_applied_until_submission_evidence": True,
        },
    }
