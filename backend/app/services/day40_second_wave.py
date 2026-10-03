"""Read-only Day 40 second-wave admission and strict post-wave certification.

Day 40 may continue the bounded live pilot only after the first live wave is complete and
clean. These evaluators never persist an authorization, enable real submission, or claim
that a live second wave occurred merely because CI exercised the tooling.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


DAY40_READINESS_VERSION = "day40-second-wave-readiness-v1"
DAY40_CERTIFICATION_VERSION = "day40-second-wave-certification-v1"
DAY40_ADAPTER = "lever"
DAY40_ADAPTER_VERSION = "1.1.0"
DAY40_REQUIRED_MATURITY = "certified_autonomous"
DAY40_MAX_ATTEMPTS = 2
DAY40_MAX_WINDOW_SECONDS = 12 * 60 * 60
DAY40_START_GRACE_SECONDS = 5 * 60
DAY40_MAX_FUTURE_START_SECONDS = 24 * 60 * 60

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sha40(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _SHA40.fullmatch(text) else ""


def _sha256(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.split(":", 1)[1]
    return text if _SHA256.fullmatch(text) else ""


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


def _int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def expected_day40_acknowledgment(*, revision: str, attempt_cap: int) -> str:
    normalized = _sha40(revision)
    cap = _int(attempt_cap, 0)
    if not normalized or cap <= 0:
        return ""
    return f"AUTHORIZE SECOND WAVE LEVER {DAY40_ADAPTER_VERSION} {normalized[:12]} {cap}"


def _first_wave_safety_checks(first_wave: Mapping[str, Any]) -> dict[str, bool]:
    attempted = _int(first_wave.get("attempted_count"), -1)
    accounted = _int(first_wave.get("accounted_attempt_count"), -1)
    return {
        "first_wave_completed": str(first_wave.get("status") or "") == "completed",
        "first_wave_attempt_count_bounded": 1 <= attempted <= DAY40_MAX_ATTEMPTS,
        "first_wave_all_attempts_accounted": attempted >= 1 and accounted == attempted,
        "first_wave_zero_critical_defects": _int(first_wave.get("critical_defect_count"), -1) == 0,
        "first_wave_zero_duplicates": _int(first_wave.get("duplicate_submission_count"), -1) == 0,
        "first_wave_zero_false_submitted_status": _int(
            first_wave.get("false_submitted_status_count"), -1
        )
        == 0,
        "first_wave_zero_wrong_targets": _int(first_wave.get("wrong_target_count"), -1) == 0,
        "first_wave_zero_guessed_required_answers": _int(
            first_wave.get("guessed_required_answer_count"), -1
        )
        == 0,
        "first_wave_zero_ambiguous_confirmations": _int(
            first_wave.get("ambiguous_confirmation_count"), -1
        )
        == 0,
        "first_wave_zero_breaker_trips": _int(first_wave.get("breaker_trip_count"), -1) == 0,
        "first_wave_zero_policy_escapes": _int(first_wave.get("policy_escape_count"), -1) == 0,
        "first_wave_zero_unresolved_outcomes": _int(
            first_wave.get("unresolved_outcome_count"), -1
        )
        == 0,
        "first_wave_evidence_reconciled": first_wave.get("confirmation_evidence_reconciled")
        is True,
        "first_wave_attempt_reservations_non_reclaiming": first_wave.get(
            "reserved_attempts_non_reclaiming"
        )
        is True,
    }


def build_day40_second_wave_readiness(
    *,
    first_wave_report: Any,
    adapter_state: Any,
    runtime_safety: Any,
    policy_state: Any,
    operations_state: Any,
    owner_request: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Decide whether a separate Day 40 continuation authorization may be created."""

    current = _aware(now) or datetime.now(timezone.utc)
    first_wave = _mapping(first_wave_report)
    adapter = _mapping(adapter_state)
    runtime = _mapping(runtime_safety)
    policy = _mapping(policy_state)
    operations = _mapping(operations_state)
    owner = _mapping(owner_request)

    first_revision = _sha40(first_wave.get("release_candidate_revision"))
    runtime_revision = _sha40(runtime.get("current_revision"))
    owner_revision = _sha40(owner.get("approved_for_commit"))
    first_hash = _sha256(first_wave.get("report_sha256"))
    attempt_cap = _int(owner.get("max_submission_attempts"), 0)
    starts_at = _aware(owner.get("starts_at"))
    expires_at = _aware(owner.get("expires_at"))
    window_seconds = (
        max(0.0, (expires_at - starts_at).total_seconds())
        if starts_at is not None and expires_at is not None
        else 0.0
    )
    expected_ack = expected_day40_acknowledgment(
        revision=first_revision,
        attempt_cap=attempt_cap,
    )

    first_wave_checks = {
        "first_wave_report_hash_valid": bool(first_hash),
        "first_wave_revision_valid": bool(first_revision),
        "first_wave_adapter_exact": str(first_wave.get("adapter") or "").lower()
        == DAY40_ADAPTER,
        "first_wave_adapter_version_exact": str(first_wave.get("adapter_version") or "")
        == DAY40_ADAPTER_VERSION,
        **_first_wave_safety_checks(first_wave),
    }

    adapter_checks = {
        "adapter_name_exact": str(adapter.get("name") or "").lower() == DAY40_ADAPTER,
        "adapter_version_exact": str(adapter.get("version") or "") == DAY40_ADAPTER_VERSION,
        "adapter_certified_autonomous": str(adapter.get("maturity") or "")
        == DAY40_REQUIRED_MATURITY,
        "adapter_autonomous_submission_capability": adapter.get(
            "autonomous_submission_allowed"
        )
        is True,
    }

    runtime_checks = {
        "runtime_revision_matches_first_wave": bool(first_revision)
        and runtime_revision == first_revision,
        "real_submission_disabled_between_waves": runtime.get(
            "allow_real_application_submit"
        )
        is False,
        "real_followup_send_disabled": runtime.get("allow_real_followup_send") is False,
        "global_kill_switch_clear": runtime.get("global_kill_switch") is False,
        "no_active_live_window": runtime.get("live_window_authorized") is False,
    }

    remaining_daily = _int(policy.get("remaining_daily"), -1)
    remaining_weekly = _int(policy.get("remaining_weekly"), -1)
    policy_checks = {
        "production_policy_ready": policy.get("ready") is True,
        "policy_profile_production": str(policy.get("policy_profile") or "") == "production",
        "circuit_breaker_clear": policy.get("circuit_breaker_clear") is True,
        "quiet_hours_clear": policy.get("quiet_hours_active") is False,
        "daily_capacity_covers_second_wave": attempt_cap > 0 and remaining_daily >= attempt_cap,
        "weekly_capacity_covers_second_wave": attempt_cap > 0 and remaining_weekly >= attempt_cap,
    }

    operations_checks = {
        "queue_prioritization_ready": operations.get("queue_prioritization_ready") is True,
        "cap_enforcement_ready": operations.get("cap_enforcement_ready") is True,
        "followup_scheduler_ready": operations.get("followup_scheduler_ready") is True,
        "confirmation_reconciliation_ready": operations.get(
            "confirmation_reconciliation_ready"
        )
        is True,
    }

    owner_checks = {
        "owner_approved": owner.get("approved") is True,
        "owner_reference_present": bool(str(owner.get("approval_reference") or "").strip()),
        "owner_commit_exact": bool(first_revision) and owner_revision == first_revision,
        "owner_adapter_exact": str(owner.get("adapter") or "").lower() == DAY40_ADAPTER,
        "owner_adapter_version_exact": str(owner.get("adapter_version") or "")
        == DAY40_ADAPTER_VERSION,
        "attempt_cap_conservative": 1 <= attempt_cap <= DAY40_MAX_ATTEMPTS,
        "window_start_valid": starts_at is not None,
        "window_expiry_valid": expires_at is not None,
        "window_not_expired": expires_at is not None and expires_at > current,
        "window_start_not_stale": starts_at is not None
        and starts_at >= current - timedelta(seconds=DAY40_START_GRACE_SECONDS),
        "window_start_not_too_far_future": starts_at is not None
        and starts_at <= current + timedelta(seconds=DAY40_MAX_FUTURE_START_SECONDS),
        "window_duration_bounded": 0 < window_seconds <= DAY40_MAX_WINDOW_SECONDS,
        "owner_acknowledgment_exact": bool(expected_ack)
        and str(owner.get("acknowledgment") or "") == expected_ack,
    }

    sections = {
        "first_wave": first_wave_checks,
        "adapter": adapter_checks,
        "runtime": runtime_checks,
        "policy": policy_checks,
        "operations": operations_checks,
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
        "version": DAY40_READINESS_VERSION,
        "evaluated_at": current.isoformat(),
        "release_candidate_revision": first_revision or None,
        "first_wave_report_sha256": first_hash or None,
        "target_adapter": DAY40_ADAPTER,
        "target_adapter_version": DAY40_ADAPTER_VERSION,
        "requested_attempt_cap": attempt_cap,
        "maximum_attempt_cap": DAY40_MAX_ATTEMPTS,
        "starts_at": starts_at.isoformat() if starts_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "window_seconds": window_seconds,
        "expected_acknowledgment": expected_ack or None,
        "checks": sections,
        "blockers": blockers,
        "second_wave_authorization_eligible": eligible,
        "authorization_persisted": False,
        "live_window_authorized": False,
        "real_submission_enabled": False,
        "real_followup_send_enabled": False,
        "invariants": {
            "day39_first_wave_must_remain_immutable": True,
            "second_wave_requires_new_owner_authorization": True,
            "worker_must_recheck_policy_and_authorization": True,
            "attempt_reservation_must_remain_atomic_and_non_reclaiming": True,
            "ci_cannot_claim_real_second_wave_completion": True,
        },
        "next_action": (
            "persist_separate_day40_authorization"
            if eligible
            else "satisfy_day40_second_wave_blockers"
        ),
    }
    result["report_sha256"] = _canonical_hash(result)
    return result


def build_day40_second_wave_certification(
    *,
    second_wave_report: Any,
    verification_revision: str,
) -> dict[str, Any]:
    """Strictly certify a completed second wave before Day 41 may begin."""

    wave = _mapping(second_wave_report)
    expected_revision = _sha40(verification_revision)
    wave_revision = _sha40(wave.get("release_candidate_revision"))
    attempted = _int(wave.get("attempted_count"), -1)
    authorized_cap = _int(wave.get("authorized_attempt_cap"), -1)
    accounted = _int(wave.get("accounted_attempt_count"), -1)

    checks = {
        "verification_revision_valid": bool(expected_revision),
        "second_wave_revision_exact": bool(expected_revision) and wave_revision == expected_revision,
        "second_wave_completed": str(wave.get("status") or "") == "completed",
        "adapter_exact": str(wave.get("adapter") or "").lower() == DAY40_ADAPTER,
        "adapter_version_exact": str(wave.get("adapter_version") or "") == DAY40_ADAPTER_VERSION,
        "attempt_cap_valid": 1 <= authorized_cap <= DAY40_MAX_ATTEMPTS,
        "attempt_count_within_authority": attempted >= 1 and attempted <= authorized_cap,
        "all_attempts_accounted": attempted >= 1 and accounted == attempted,
        "zero_critical_defects": _int(wave.get("critical_defect_count"), -1) == 0,
        "zero_duplicates": _int(wave.get("duplicate_submission_count"), -1) == 0,
        "zero_false_submitted_status": _int(wave.get("false_submitted_status_count"), -1) == 0,
        "zero_wrong_targets": _int(wave.get("wrong_target_count"), -1) == 0,
        "zero_guessed_required_answers": _int(wave.get("guessed_required_answer_count"), -1) == 0,
        "zero_ambiguous_confirmations": _int(wave.get("ambiguous_confirmation_count"), -1) == 0,
        "zero_breaker_trips": _int(wave.get("breaker_trip_count"), -1) == 0,
        "zero_policy_escapes": _int(wave.get("policy_escape_count"), -1) == 0,
        "zero_unresolved_outcomes": _int(wave.get("unresolved_outcome_count"), -1) == 0,
        "queue_prioritization_exercised": wave.get("queue_prioritization_exercised") is True,
        "cap_enforcement_exercised": wave.get("cap_enforcement_exercised") is True,
        "followup_scheduling_exercised": wave.get("followup_scheduling_exercised") is True,
        "confirmation_evidence_reconciled": wave.get("confirmation_evidence_reconciled") is True,
        "external_confirmation_comparison_accounted": wave.get(
            "platform_external_evidence_compared"
        )
        is True
        or wave.get("external_confirmation_unavailable_documented") is True,
        "reserved_attempts_non_reclaiming": wave.get("reserved_attempts_non_reclaiming") is True,
        "live_window_closed_after_wave": wave.get("live_window_closed") is True,
        "real_submission_disabled_after_wave": wave.get("real_submission_disabled_after_wave")
        is True,
        "real_followup_send_disabled": wave.get("real_followup_send_disabled") is True,
    }
    blockers = [name for name, passed in checks.items() if not passed]
    passed = not blockers
    result: dict[str, Any] = {
        "version": DAY40_CERTIFICATION_VERSION,
        "release_candidate_revision": expected_revision or None,
        "checks": checks,
        "blockers": blockers,
        "passed": passed,
        "day41_entry_eligible": passed,
        "invariants": {
            "sustained_zero_false_positive_submission_status_required": True,
            "sustained_zero_duplicates_required": True,
            "day41_requires_live_mode_disabled": True,
        },
    }
    result["report_sha256"] = _canonical_hash(result)
    return result


__all__ = [
    "DAY40_ADAPTER",
    "DAY40_ADAPTER_VERSION",
    "DAY40_CERTIFICATION_VERSION",
    "DAY40_MAX_ATTEMPTS",
    "DAY40_READINESS_VERSION",
    "build_day40_second_wave_certification",
    "build_day40_second_wave_readiness",
    "expected_day40_acknowledgment",
]
