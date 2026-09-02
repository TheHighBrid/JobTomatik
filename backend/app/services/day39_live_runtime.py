"""Canonical runtime inputs and worker authority for the Day 39 live pilot.

The API and worker must never trust caller-supplied claims about adapter maturity,
promotion state, release revision, or policy readiness. Those values are reconstructed
from the signed ATS manifest, exact runtime identity, current operations policy, and
durable live-pilot authorization records.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

from app.config import get_settings
from app.models.live_pilot import LivePilotAuthorization
from app.services.ats_manifest import ats_certification_manifest
from app.services.day39_live_authorization import reserve_live_pilot_attempt
from app.services.day39_live_window import (
    DAY39_LIVE_ADAPTER,
    DAY39_LIVE_ADAPTER_VERSION,
    DAY39_LIVE_REQUIRED_MATURITY,
)
from app.services.operations_policy import evaluate_autopilot_policy
from app.services.operations_settings import get_operations_settings
from app.services.runtime_identity import runtime_identity_manifest


DAY39_LIVE_RUNTIME_VERSION = "day39-live-runtime-authority-v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


def _aware(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _sha40(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _SHA40.fullmatch(text) else ""


def canonical_lever_adapter_state(manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return the signed canonical Lever maturity state and release binding."""

    source = manifest if isinstance(manifest, Mapping) else ats_certification_manifest()
    adapter = next(
        (
            dict(item)
            for item in source.get("adapters", [])
            if isinstance(item, Mapping)
            and str(item.get("name") or "").strip().lower() == DAY39_LIVE_ADAPTER
        ),
        {},
    )
    release = dict((adapter.get("release_gate_status") or {}).get("certified_autonomous") or {})
    certification = dict(release.get("certification_manifest") or {})
    release_commit = _sha40(certification.get("release_commit"))
    adapter["autonomy_release_valid"] = bool(
        release.get("passed") is True
        and certification.get("passed") is True
        and release_commit
    )
    adapter["autonomy_release_commit"] = release_commit or None
    return adapter


def _active_window_exists(db, *, user_id: int, now: datetime) -> bool:
    return (
        db.query(LivePilotAuthorization.id)
        .filter(
            LivePilotAuthorization.approved_by_user_id == int(user_id),
            LivePilotAuthorization.status == "approved",
            LivePilotAuthorization.revoked_at.is_(None),
            LivePilotAuthorization.expires_at > now,
        )
        .first()
        is not None
    )


def build_canonical_day39_live_context(
    db,
    user,
    *,
    now: datetime | None = None,
    manifest: Mapping[str, Any] | None = None,
    runtime_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the only API-side inputs accepted by the live-window evaluator."""

    current = _aware(now)
    adapter = canonical_lever_adapter_state(manifest)
    release_revision = _sha40(adapter.get("autonomy_release_commit"))
    runtime = dict(runtime_manifest or runtime_identity_manifest())
    runtime_revision = _sha40(runtime.get("revision"))
    core = get_settings()
    operations = get_operations_settings()

    # The production policy is evaluated at authorization time. If it is blocked by
    # quiet hours, caps, pause, or a breaker, readiness fails closed. Missing capacity
    # metadata is represented as -1, which cannot satisfy the bounded-window evaluator.
    policy_now = current.replace(tzinfo=None)
    policy_decision = evaluate_autopilot_policy(
        db,
        user,
        policy_now,
        policy_profile="production",
    )
    policy_meta = dict(policy_decision.metadata or {})

    adapter_is_autonomous = bool(
        str(adapter.get("name") or "").strip().lower() == DAY39_LIVE_ADAPTER
        and str(adapter.get("version") or "").strip() == DAY39_LIVE_ADAPTER_VERSION
        and str(adapter.get("maturity") or "").strip() == DAY39_LIVE_REQUIRED_MATURITY
        and adapter.get("autonomous_submission_allowed") is True
        and adapter.get("autonomy_release_valid") is True
        and release_revision
    )
    promotion = {
        "passed": adapter_is_autonomous,
        "promotion_authorized": adapter_is_autonomous,
        "live_window_authorized": False,
        "real_submission_authorized": False,
        "release_candidate_revision": release_revision or None,
        "target_adapter": DAY39_LIVE_ADAPTER,
        "target_adapter_version": DAY39_LIVE_ADAPTER_VERSION,
        "target_maturity": DAY39_LIVE_REQUIRED_MATURITY,
    }

    runtime_attested = bool(
        runtime.get("deployment_attested") is True
        and runtime.get("known") is True
        and runtime_revision
    )
    runtime_safety = {
        "current_revision": runtime_revision if runtime_attested else None,
        "allow_real_application_submit": bool(core.allow_real_application_submit),
        "allow_real_followup_send": bool(core.allow_real_followup_send),
        "global_kill_switch": bool(operations.global_kill_switch),
        "live_window_authorized": _active_window_exists(
            db,
            user_id=int(user.id),
            now=current,
        ),
        "deployment_attested": runtime_attested,
    }

    code = str(policy_decision.code or "")
    policy_state = {
        "ready": policy_decision.allowed is True,
        "policy_profile": "production",
        "circuit_breaker_clear": code not in {
            "circuit_breaker_open",
            "platform_circuit_breaker_open",
            "global_kill_switch_active",
        },
        "quiet_hours_active": code == "quiet_hours",
        "remaining_daily": int(policy_meta.get("remaining_daily", -1)),
        "remaining_weekly": int(policy_meta.get("remaining_weekly", -1)),
        "decision": policy_decision.to_dict(),
    }

    return {
        "version": DAY39_LIVE_RUNTIME_VERSION,
        "evaluated_at": current.isoformat(),
        "promotion": promotion,
        "adapter_state": adapter,
        "runtime_safety": runtime_safety,
        "policy_state": policy_state,
    }


def reserve_canonical_day39_live_attempt(
    db,
    *,
    user_id: int,
    application_id: int,
    platform: str,
    now: datetime | None = None,
    manifest: Mapping[str, Any] | None = None,
    runtime_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Fail closed unless one exact live authorization may fund this browser attempt."""

    current = _aware(now)
    if str(platform or "").strip().lower() != DAY39_LIVE_ADAPTER:
        return {"allowed": False, "reason": "day39_live_pilot_adapter_not_authorized"}

    core = get_settings()
    operations = get_operations_settings()
    if core.allow_real_application_submit is not True:
        return {"allowed": False, "reason": "real_submission_runtime_disabled"}
    if core.allow_real_followup_send is not False:
        return {"allowed": False, "reason": "real_followup_send_must_remain_disabled"}
    if operations.global_kill_switch:
        return {"allowed": False, "reason": "global_kill_switch_active"}

    adapter = canonical_lever_adapter_state(manifest)
    if not (
        str(adapter.get("version") or "") == DAY39_LIVE_ADAPTER_VERSION
        and str(adapter.get("maturity") or "") == DAY39_LIVE_REQUIRED_MATURITY
        and adapter.get("autonomous_submission_allowed") is True
        and adapter.get("autonomy_release_valid") is True
    ):
        return {"allowed": False, "reason": "lever_not_certified_autonomous"}

    release_revision = _sha40(adapter.get("autonomy_release_commit"))
    runtime = dict(runtime_manifest or runtime_identity_manifest())
    runtime_revision = _sha40(runtime.get("revision"))
    if not (
        release_revision
        and runtime_revision == release_revision
        and runtime.get("deployment_attested") is True
        and runtime.get("known") is True
    ):
        return {"allowed": False, "reason": "live_pilot_runtime_revision_unattested"}

    result = reserve_live_pilot_attempt(
        db,
        user_id=int(user_id),
        application_id=int(application_id),
        adapter=DAY39_LIVE_ADAPTER,
        adapter_version=DAY39_LIVE_ADAPTER_VERSION,
        revision=runtime_revision,
        now=current,
    )
    return {**result, "runtime_revision": runtime_revision}


__all__ = [
    "DAY39_LIVE_RUNTIME_VERSION",
    "build_canonical_day39_live_context",
    "canonical_lever_adapter_state",
    "reserve_canonical_day39_live_attempt",
]
