"""Read-only Day 39 promotion readiness evaluator.

This module prepares the post-shadow promotion decision without changing adapter maturity,
enabling real submission, authorizing a live window, or manufacturing missing evidence.
Day 38 may be on an older retained revision. The Day 39 release candidate must instead
be bound to its own exact-head release matrix and a separate owner approval.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


DAY39_PROMOTION_READINESS_VERSION = "day39-promotion-readiness-v1"
DAY39_TARGET_ADAPTER = "lever"
DAY39_TARGET_ADAPTER_VERSION = "1.1.0"
DAY39_REQUIRED_MATURITY_BEFORE_PROMOTION = "dry_run"
DAY39_TARGET_MATURITY = "certified_autonomous"
DAY39_MIN_DAY38_ELAPSED_SECONDS = 24 * 60 * 60
DAY39_MIN_POLICY_OBSERVATION_SECONDS = 23 * 60 * 60

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

DAY39_REQUIRED_DAY38_POLICY_CHECKS = (
    "every_completed_cycle_has_policy_diagnostic",
    "policy_diagnostic_version_exact",
    "production_diagnostic_never_authoritative",
    "shadow_execution_profile_remained_shadow_test",
    "policy_diagnostic_never_changed_execution_authority",
    "quiet_hours_configuration_stable",
    "quiet_hours_transition_observed",
    "rolling_24h_cap_stable",
    "rolling_24h_semantics_exact",
    "rolling_24h_window_observed_across_full_run",
    "rolling_24h_membership_rollover_observed",
)

DAY39_REQUIRED_RELEASE_WORKFLOWS = (
    "Backend tests",
    "Post-merge stabilization",
    "Reproducible verification",
    "CodeQL security analysis",
    "Current-head end-to-end acceptance",
    "Android runtime dispatch acceptance",
    "Full-stack shadow campaigns",
    "Day 38 shadow endurance tooling gate",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bool(value: Any) -> bool:
    return value is True


def _sha40(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _SHA40.fullmatch(text) else ""


def _sha256(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.split(":", 1)[1]
    return text if _SHA256.fullmatch(text) else ""


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_day39_promotion_readiness(
    *,
    day38_report: Any,
    day38_review: Any,
    release_matrix: Any,
    adapter_state: Any,
    runtime_safety: Any,
    owner_approval: Any = None,
) -> dict[str, Any]:
    """Evaluate whether a separate Day 39 maturity-promotion change may be opened.

    A technically ready result is still not owner approval and never authorizes a live
    submission window. Full ``passed`` requires a separate owner approval bound to the
    exact release-candidate commit, adapter, and version.
    """

    shadow = _mapping(day38_report)
    review = _mapping(day38_review)
    matrix = _mapping(release_matrix)
    adapter = _mapping(adapter_state)
    safety = _mapping(runtime_safety)
    approval = _mapping(owner_approval)

    shadow_revision = _sha40(shadow.get("candidate_revision"))
    shadow_report_sha = _sha256(shadow.get("report_sha256"))
    verification_revision = _sha40(matrix.get("revision"))

    policy = _mapping(shadow.get("production_policy_transitions"))
    policy_checks = _mapping(policy.get("checks"))
    rolling = _mapping(policy.get("rolling_24h_capacity"))
    aged_out = list(rolling.get("aged_out_member_application_ids") or [])
    try:
        policy_span = float(policy.get("observation_span_seconds") or 0.0)
    except (TypeError, ValueError):
        policy_span = 0.0
    try:
        elapsed = float(shadow.get("persisted_elapsed_seconds") or 0.0)
    except (TypeError, ValueError):
        elapsed = 0.0

    day38_checks = {
        "strict_day38_passed": _bool(shadow.get("passed")),
        "day39_entry_eligible": _bool(shadow.get("day39_entry_eligible")),
        "day38_target_exact": str(shadow.get("target_evidence_type") or "")
        == "shadow_run_24h",
        "day38_revision_valid": bool(shadow_revision),
        "day38_report_hash_valid": bool(shadow_report_sha),
        "day38_elapsed_at_least_24h": elapsed >= DAY39_MIN_DAY38_ELAPSED_SECONDS,
        "day38_policy_observation_span": policy_span
        >= DAY39_MIN_POLICY_OBSERVATION_SECONDS,
        "day38_rolling_semantics_exact": str(rolling.get("semantics") or "")
        == "rolling_previous_24_hours",
        "day38_real_membership_rollover": bool(aged_out),
    }
    for name in DAY39_REQUIRED_DAY38_POLICY_CHECKS:
        day38_checks[f"day38_policy:{name}"] = policy_checks.get(name) is True

    review_commit = _sha40(review.get("commit_sha"))
    review_report_sha = _sha256(review.get("strict_report_sha256"))
    review_checks = {
        "day38_evidence_id_present": isinstance(review.get("evidence_id"), int)
        and not isinstance(review.get("evidence_id"), bool)
        and int(review.get("evidence_id")) > 0,
        "day38_review_verified": str(review.get("review_status") or "") == "verified",
        "day38_review_reference_present": bool(
            str(review.get("review_reference") or "").strip()
        ),
        "day38_review_commit_matches_report": bool(shadow_revision)
        and review_commit == shadow_revision,
        "day38_review_binds_strict_report": bool(shadow_report_sha)
        and review_report_sha == shadow_report_sha,
    }

    workflows = _mapping(matrix.get("workflows"))
    release_checks = {
        "release_revision_valid": bool(verification_revision),
        "release_matrix_exact_head": _sha40(matrix.get("current_head"))
        == verification_revision
        and bool(verification_revision),
        "release_matrix_passed": matrix.get("passed") is True,
    }
    for workflow_name in DAY39_REQUIRED_RELEASE_WORKFLOWS:
        release_checks[f"workflow:{workflow_name}"] = (
            str(workflows.get(workflow_name) or "").strip().lower() == "success"
        )

    adapter_checks = {
        "adapter_name_exact": str(adapter.get("name") or "").lower()
        == DAY39_TARGET_ADAPTER,
        "adapter_version_exact": str(adapter.get("version") or "")
        == DAY39_TARGET_ADAPTER_VERSION,
        "adapter_still_dry_run": str(adapter.get("maturity") or "")
        == DAY39_REQUIRED_MATURITY_BEFORE_PROMOTION,
        "adapter_not_already_autonomous": adapter.get("autonomous_submission_allowed")
        is False,
    }

    safety_checks = {
        "real_submission_still_disabled": safety.get("allow_real_application_submit")
        is False,
        "real_followup_send_still_disabled": safety.get("allow_real_followup_send")
        is False,
        "live_window_not_pre_authorized": safety.get("live_window_authorized") is False,
    }

    technical_sections = {
        "day38": day38_checks,
        "day38_review": review_checks,
        "release_matrix": release_checks,
        "adapter": adapter_checks,
        "runtime_safety": safety_checks,
    }
    technical_blockers = [
        f"{section}.{name}"
        for section, checks in technical_sections.items()
        for name, passed in checks.items()
        if not passed
    ]
    technical_ready = not technical_blockers

    owner_checks = {
        "owner_approved": approval.get("approved") is True,
        "owner_reference_present": bool(
            str(approval.get("approval_reference") or "").strip()
        ),
        "owner_release_commit_exact": bool(verification_revision)
        and _sha40(approval.get("approved_for_commit")) == verification_revision,
        "owner_adapter_exact": str(approval.get("adapter") or "").lower()
        == DAY39_TARGET_ADAPTER,
        "owner_adapter_version_exact": str(approval.get("adapter_version") or "")
        == DAY39_TARGET_ADAPTER_VERSION,
        "owner_target_maturity_exact": str(approval.get("target_maturity") or "")
        == DAY39_TARGET_MATURITY,
    }
    owner_blockers = [name for name, passed in owner_checks.items() if not passed]
    owner_gate_passed = not owner_blockers

    passed = bool(technical_ready and owner_gate_passed)
    result: dict[str, Any] = {
        "version": DAY39_PROMOTION_READINESS_VERSION,
        "target_adapter": DAY39_TARGET_ADAPTER,
        "target_adapter_version": DAY39_TARGET_ADAPTER_VERSION,
        "target_maturity": DAY39_TARGET_MATURITY,
        "day38_candidate_revision": shadow_revision or None,
        "release_candidate_revision": verification_revision or None,
        "technical_checks": technical_sections,
        "technical_ready": technical_ready,
        "technical_blockers": technical_blockers,
        "owner_approval_checks": owner_checks,
        "owner_approval_required": not owner_gate_passed,
        "owner_approval_blockers": owner_blockers,
        "passed": passed,
        "promotion_authorized": passed,
        "live_window_authorized": False,
        "real_submission_authorized": False,
        "invariants": {
            "day38_revision_may_precede_release_candidate": True,
            "release_matrix_must_bind_exact_current_head": True,
            "owner_approval_must_bind_exact_release_candidate": True,
            "promotion_does_not_authorize_live_window": True,
            "legacy_utc_midnight_daily_reset_is_not_a_day38_requirement": True,
            "rolling_capacity_semantics": "rolling_previous_24_hours",
        },
        "next_action": (
            "open_separate_promotion_change"
            if passed
            else (
                "obtain_owner_promotion_approval"
                if technical_ready
                else "satisfy_technical_promotion_blockers"
            )
        ),
    }
    result["report_sha256"] = _canonical_hash(result)
    return result


__all__ = [
    "DAY39_PROMOTION_READINESS_VERSION",
    "DAY39_REQUIRED_DAY38_POLICY_CHECKS",
    "DAY39_REQUIRED_RELEASE_WORKFLOWS",
    "DAY39_TARGET_ADAPTER",
    "DAY39_TARGET_ADAPTER_VERSION",
    "build_day39_promotion_readiness",
]
