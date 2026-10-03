"""Fail-closed Day 39 bounded live-window readiness evaluator.

This module deliberately does not persist an authorization, mutate adapter maturity,
or enable real submission. It validates the narrow owner request that may later be
persisted only after the exact release candidate is already certified autonomous.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


DAY39_LIVE_WINDOW_VERSION = "day39-live-window-readiness-v1"
DAY39_LIVE_ADAPTER = "lever"
DAY39_LIVE_ADAPTER_VERSION = "1.1.0"
DAY39_LIVE_REQUIRED_MATURITY = "certified_autonomous"
DAY39_LIVE_MAX_ATTEMPTS = 2
DAY39_LIVE_MAX_WINDOW_SECONDS = 12 * 60 * 60
DAY39_LIVE_MAX_FUTURE_START_SECONDS = 24 * 60 * 60
DAY39_LIVE_START_GRACE_SECONDS = 5 * 60

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sha40(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _SHA40.fullmatch(text) else ""


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def expected_live_window_acknowledgment(
    *,
    revision: str,
    attempt_cap: int,
) -> str:
    """Return the exact owner phrase for one bounded first-wave authorization."""

    normalized = _sha40(revision)
    if not normalized:
        return ""
    try:
        cap = int(attempt_cap)
    except (TypeError, ValueError):
        return ""
    return (
        f"AUTHORIZE LIVE PILOT {DAY39_LIVE_ADAPTER.upper()} "
        f"{DAY39_LIVE_ADAPTER_VERSION} {normalized[:12]} {cap}"
    )


def build_day39_live_window_readiness(
    *,
    promotion: Any,
    adapter_state: Any,
    runtime_safety: Any,
    policy_state: Any,
    owner_request: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a future bounded live-pilot authorization without granting it.

    The evaluator requires a completed exact-head Day 39 promotion first. It also
    requires real submission to remain disabled while the authorization request is
    being evaluated, preventing the global runtime flag from becoming authority by
    itself. The later worker integration must re-check this authorization immediately
    before consequential browser work and reserve attempts atomically.
    """

    current = _aware(now) or datetime.now(timezone.utc)
    promo = _mapping(promotion)
    adapter = _mapping(adapter_state)
    runtime = _mapping(runtime_safety)
    policy = _mapping(policy_state)
    owner = _mapping(owner_request)

    release_revision = _sha40(promo.get("release_candidate_revision"))
    runtime_revision = _sha40(runtime.get("current_revision"))
    owner_revision = _sha40(owner.get("approved_for_commit"))

    try:
        attempt_cap = int(owner.get("max_submission_attempts"))
    except (TypeError, ValueError):
        attempt_cap = 0

    starts_at = _aware(owner.get("starts_at"))
    expires_at = _aware(owner.get("expires_at"))
    window_seconds = (
        max(0.0, (expires_at - starts_at).total_seconds())
        if starts_at is not None and expires_at is not None
        else 0.0
    )

    expected_ack = expected_live_window_acknowledgment(
        revision=release_revision,
        attempt_cap=attempt_cap,
    )

    promotion_checks = {
        "promotion_passed": promo.get("passed") is True,
        "promotion_authorized": promo.get("promotion_authorized") is True,
        "promotion_did_not_pre_authorize_live_window": promo.get("live_window_authorized")
        is False,
        "promotion_did_not_authorize_real_submission": promo.get("real_submission_authorized")
        is False,
        "promotion_revision_valid": bool(release_revision),
        "promotion_adapter_exact": str(promo.get("target_adapter") or "").lower()
        == DAY39_LIVE_ADAPTER,
        "promotion_adapter_version_exact": str(
            promo.get("target_adapter_version") or ""
        )
        == DAY39_LIVE_ADAPTER_VERSION,
        "promotion_target_maturity_exact": str(promo.get("target_maturity") or "")
        == DAY39_LIVE_REQUIRED_MATURITY,
    }

    adapter_checks = {
        "adapter_name_exact": str(adapter.get("name") or "").lower()
        == DAY39_LIVE_ADAPTER,
        "adapter_version_exact": str(adapter.get("version") or "")
        == DAY39_LIVE_ADAPTER_VERSION,
        "adapter_certified_autonomous": str(adapter.get("maturity") or "")
        == DAY39_LIVE_REQUIRED_MATURITY,
        "adapter_autonomous_submission_capability": adapter.get(
            "autonomous_submission_allowed"
        )
        is True,
    }

    runtime_checks = {
        "runtime_revision_exact": bool(release_revision)
        and runtime_revision == release_revision,
        "real_submission_still_disabled_during_authorization": runtime.get(
            "allow_real_application_submit"
        )
        is False,
        "real_followup_send_disabled": runtime.get("allow_real_followup_send") is False,
        "global_kill_switch_clear": runtime.get("global_kill_switch") is False,
        "no_existing_live_window": runtime.get("live_window_authorized") is False,
    }

    try:
        remaining_daily = int(policy.get("remaining_daily"))
    except (TypeError, ValueError):
        remaining_daily = -1
    try:
        remaining_weekly = int(policy.get("remaining_weekly"))
    except (TypeError, ValueError):
        remaining_weekly = -1

    policy_checks = {
        "production_policy_ready": policy.get("ready") is True,
        "policy_profile_production": str(policy.get("policy_profile") or "")
        == "production",
        "circuit_breaker_clear": policy.get("circuit_breaker_clear") is True,
        "quiet_hours_clear_at_authorization": policy.get("quiet_hours_active") is False,
        "daily_capacity_covers_window": attempt_cap > 0
        and remaining_daily >= attempt_cap,
        "weekly_capacity_covers_window": attempt_cap > 0
        and remaining_weekly >= attempt_cap,
    }

    owner_checks = {
        "owner_approved": owner.get("approved") is True,
        "owner_reference_present": bool(str(owner.get("approval_reference") or "").strip()),
        "owner_commit_exact": bool(release_revision) and owner_revision == release_revision,
        "owner_adapter_exact": str(owner.get("adapter") or "").lower()
        == DAY39_LIVE_ADAPTER,
        "owner_adapter_version_exact": str(owner.get("adapter_version") or "")
        == DAY39_LIVE_ADAPTER_VERSION,
        "attempt_cap_is_conservative": 1 <= attempt_cap <= DAY39_LIVE_MAX_ATTEMPTS,
        "window_start_valid": starts_at is not None,
        "window_expiry_valid": expires_at is not None,
        "window_not_expired": expires_at is not None and expires_at > current,
        "window_start_not_stale": starts_at is not None
        and starts_at >= current - timedelta(seconds=DAY39_LIVE_START_GRACE_SECONDS),
        "window_start_not_too_far_future": starts_at is not None
        and starts_at <= current + timedelta(seconds=DAY39_LIVE_MAX_FUTURE_START_SECONDS),
        "window_duration_bounded": 0 < window_seconds <= DAY39_LIVE_MAX_WINDOW_SECONDS,
        "owner_acknowledgment_exact": bool(expected_ack)
        and str(owner.get("acknowledgment") or "") == expected_ack,
    }

    sections = {
        "promotion": promotion_checks,
        "adapter": adapter_checks,
        "runtime": runtime_checks,
        "policy": policy_checks,
        "owner": owner_checks,
    }
    blockers = [
        f"{section}.{name}"
        for section, checks in sections.items()
        for name, passed in checks.items()
        if not passed
    ]
    eligible = not blockers

    result: dict[str, Any] = {
        "version": DAY39_LIVE_WINDOW_VERSION,
        "evaluated_at": current.isoformat(),
        "target_adapter": DAY39_LIVE_ADAPTER,
        "target_adapter_version": DAY39_LIVE_ADAPTER_VERSION,
        "release_candidate_revision": release_revision or None,
        "requested_attempt_cap": attempt_cap,
        "maximum_attempt_cap": DAY39_LIVE_MAX_ATTEMPTS,
        "starts_at": starts_at.isoformat() if starts_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "window_seconds": window_seconds,
        "expected_acknowledgment": expected_ack or None,
        "checks": sections,
        "blockers": blockers,
        "authorization_eligible": eligible,
        "authorization_persisted": False,
        "live_window_authorized": False,
        "real_submission_enabled": False,
        "invariants": {
            "promotion_precedes_live_window": True,
            "global_submit_flag_is_not_authority": True,
            "worker_must_recheck_before_browser_work": True,
            "attempt_reservation_must_be_atomic": True,
            "reserved_attempts_are_not_reclaimed_after_uncertain_outcome": True,
            "followup_send_remains_separately_disabled": True,
        },
        "next_action": (
            "persist_separate_owner_live_window_authorization"
            if eligible
            else "satisfy_live_window_authorization_blockers"
        ),
    }
    result["report_sha256"] = _canonical_hash(result)
    return result


__all__ = [
    "DAY39_LIVE_ADAPTER",
    "DAY39_LIVE_ADAPTER_VERSION",
    "DAY39_LIVE_MAX_ATTEMPTS",
    "DAY39_LIVE_MAX_WINDOW_SECONDS",
    "DAY39_LIVE_REQUIRED_MATURITY",
    "DAY39_LIVE_WINDOW_VERSION",
    "build_day39_live_window_readiness",
    "expected_live_window_acknowledgment",
]
