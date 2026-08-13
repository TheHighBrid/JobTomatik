"""Pre-campaign policy readiness for Phase 11 shadow evidence runs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services.operations_policy import evaluate_autopilot_policy, is_quiet_hour
from app.services.operations_settings import get_operations_settings
from app.services.public_ats_discovery import PublicATSDiscoveryError, normalize_target
from app.services.scheduler_policy import scheduler_settings
from app.services.unattended_policy import (
    REQUIRED_SCHEDULER_POLICY_VERSION,
    SHADOW_DRY_RUN_ALLOWED_MATURITIES,
    live_platform_maturities,
)


def _bounded_hour(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(23, max(0, parsed))


def _eligible_shadow_ats_targets(user) -> list[dict[str, str]]:
    """Return explicit account-owned public ATS targets eligible for no-submit shadow work.

    Broad boards can prove discovery, but they are not deterministic application-path
    evidence. Public ATS discovery intentionally requires explicit account configuration,
    and qualification may use only adapters whose canonical maturity is already allowed
    by the existing Phase 11 no-submit exception.
    """

    maturities = live_platform_maturities()
    result: list[dict[str, str]] = []
    preferences = dict(user.job_preferences or {})
    for raw in preferences.get("ats_targets") or []:
        if not isinstance(raw, dict):
            continue
        try:
            target = normalize_target(raw)
        except PublicATSDiscoveryError:
            continue
        provider = target["provider"]
        maturity = maturities.get(provider)
        if maturity not in SHADOW_DRY_RUN_ALLOWED_MATURITIES:
            continue
        result.append(
            {
                "provider": provider,
                "identifier": target["identifier"],
                "company": target["company"],
                "maturity": str(maturity),
            }
        )
    return result


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
    eligible_targets = _eligible_shadow_ats_targets(user)

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
    daily_capacity_evaluated = "remaining_daily" in metadata
    weekly_capacity_evaluated = "remaining_weekly" in metadata
    remaining_daily = (
        int(metadata.get("remaining_daily") or 0)
        if daily_capacity_evaluated
        else None
    )
    remaining_weekly = (
        int(metadata.get("remaining_weekly") or 0)
        if weekly_capacity_evaluated
        else None
    )
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
        # Some policy verdicts intentionally short-circuit before capacity is counted
        # (for example quiet hours). Unknown capacity must never be rendered as zero
        # remaining; the real cap check becomes authoritative once it is evaluated.
        "daily_capacity_headroom": (
            True
            if not daily_capacity_evaluated
            else remaining_daily >= required_remaining
        ),
        "weekly_capacity_headroom": (
            True
            if not weekly_capacity_evaluated
            else remaining_weekly >= required_remaining
        ),
        "circuit_breaker_clear": decision.code not in {
            "circuit_breaker_open",
            "platform_circuit_breaker_open",
        },
        "shadow_eligible_public_ats_target_configured": bool(eligible_targets),
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not blockers,
        "checks": checks,
        "blockers": blockers,
        "required_remaining_applications": required_remaining,
        "remaining_daily": remaining_daily,
        "remaining_weekly": remaining_weekly,
        "daily_capacity_evaluated": daily_capacity_evaluated,
        "weekly_capacity_evaluated": weekly_capacity_evaluated,
        "quiet_hours_start_utc": start_hour,
        "quiet_hours_end_utc": end_hour,
        "quiet_hours_collision_at": quiet_collision_at,
        "scheduler_policy_version": current_policy_version or None,
        "required_scheduler_policy_version": REQUIRED_SCHEDULER_POLICY_VERSION,
        "eligible_shadow_ats_targets": eligible_targets,
        "shadow_allowed_maturities": sorted(SHADOW_DRY_RUN_ALLOWED_MATURITIES),
        "autopilot_decision": decision.to_dict(),
        "scheduler": scheduler,
    }
