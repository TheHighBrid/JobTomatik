"""Pre-campaign policy readiness for Phase 11 shadow evidence runs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services.operations_policy import evaluate_autopilot_policy, is_quiet_hour
from app.services.operations_settings import get_operations_settings
from app.services.scheduler_policy import scheduler_settings
from app.services.unattended_policy import REQUIRED_SCHEDULER_POLICY_VERSION


def _bounded_hour(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(23, max(0, parsed))


def campaign_policy_readiness(
    db,
    user,
    *,
    requested_duration_seconds: int,
    required_remaining_applications: int = 1,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Explain whether policy can support the whole requested evidence window.

    This is diagnostic admission evidence, not a replacement for production policy.
    The qualification canary still runs a real candidate through the real scheduler,
    unattended policy, queue, worker, browser and dry-run boundary.
    """

    current = now or datetime.utcnow()
    user_settings = dict(user.automation_settings or {})
    scheduler = dict(scheduler_settings(user) or {})
    operations = get_operations_settings()
    decision = evaluate_autopilot_policy(db, user, now=current)
    metadata = dict(decision.metadata or {})

    start_hour = _bounded_hour(
        user_settings.get("quiet_hours_start_utc"), operations.quiet_hours_start_utc
    )
    end_hour = _bounded_hour(
        user_settings.get("quiet_hours_end_utc"), operations.quiet_hours_end_utc
    )
    # Include the Phase 11 settle allowance because application work can legitimately
    # remain active after the evidence timer. Sampling by minute is deterministic and
    # bounded even for the 24h campaign.
    requested_window = max(0, int(requested_duration_seconds)) + (45 * 60)
    quiet_collision_at = None
    for offset_minutes in range(0, requested_window // 60 + 2):
        candidate = current + timedelta(minutes=offset_minutes)
        if is_quiet_hour(candidate, start_hour, end_hour):
            quiet_collision_at = candidate.isoformat()
            break

    required_remaining = max(1, int(required_remaining_applications))
    remaining_daily = int(metadata.get("remaining_daily", 0) or 0)
    remaining_weekly = int(metadata.get("remaining_weekly", 0) or 0)
    current_policy_version = str(user_settings.get("scheduler_policy_version") or "")

    checks = {
        "scheduler_policy_version_current": (
            current_policy_version == REQUIRED_SCHEDULER_POLICY_VERSION
        ),
        "scheduler_auto_search_enabled": bool(scheduler.get("auto_search_enabled")),
        "scheduler_auto_apply_enabled": bool(scheduler.get("auto_apply_enabled")),
        "scheduler_dry_run_enabled": bool(scheduler.get("dry_run_mode", True)),
        "autopilot_policy_currently_allowed": bool(decision.allowed),
        "quiet_hours_clear_for_requested_window": quiet_collision_at is None,
        "daily_capacity_headroom": remaining_daily >= required_remaining,
        "weekly_capacity_headroom": remaining_weekly >= required_remaining,
        "circuit_breaker_clear": decision.code not in {
            "circuit_breaker_open",
            "platform_circuit_breaker_open",
        },
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not blockers,
        "checks": checks,
        "blockers": blockers,
        "required_remaining_applications": required_remaining,
        "remaining_daily": remaining_daily,
        "remaining_weekly": remaining_weekly,
        "quiet_hours_start_utc": start_hour,
        "quiet_hours_end_utc": end_hour,
        "quiet_hours_collision_at": quiet_collision_at,
        "scheduler_policy_version": current_policy_version or None,
        "required_scheduler_policy_version": REQUIRED_SCHEDULER_POLICY_VERSION,
        "autopilot_decision": decision.to_dict(),
        "scheduler": scheduler,
    }
