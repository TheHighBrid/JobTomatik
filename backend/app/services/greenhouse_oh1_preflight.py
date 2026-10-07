"""Read-only readiness gate for the first OneHost Greenhouse acceptance.

GH-OH1 preflight composes existing canonical evidence. It never opens a browser,
changes an execution flag, issues or consumes an approval, queues work, or performs
a submission.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import Application, SubmissionEvidence
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services.operations_settings import get_operations_settings
from app.services.submission_integrity import (
    build_submission_identity_aliases,
    find_submission_identity_conflict,
)
from app.services.supervised_pilot_dossier import build_supervised_pilot_dossier


PREFLIGHT_VERSION = "1.0.0"
READY_STATUS = "READY FOR SUPERVISED EXECUTION"
BLOCKED_STATUS = "BLOCKED"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_naive(value: Any) -> datetime | None:
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _runtime_contract() -> Dict[str, Any]:
    settings = get_settings()
    operations = get_operations_settings()
    runtime_revision = _text(os.getenv("JOBTOMATIK_RUNTIME_REVISION")).lower()
    expected_revision = _text(os.getenv("JOBTOMATIK_EXPECTED_REVISION")).lower()
    runtime_mode = _text(os.getenv("JOBTOMATIK_RUNTIME_MODE")).lower()

    return {
        "runtime_mode": runtime_mode,
        "runtime_revision": runtime_revision,
        "expected_revision": expected_revision,
        "browser_provider": _text(settings.application_browser_provider),
        "external_cdp_endpoint_configured": bool(
            _text(settings.application_browser_cdp_endpoint)
        ),
        "browser_node_id": _text(settings.jobtomatik_browser_node_id),
        "browser_profile_dir": _text(settings.application_browser_profile_dir),
        "handoff_storage_dir": _text(settings.handoff_storage_dir),
        "resumable_handoffs_enabled": bool(settings.enable_resumable_handoffs),
        "global_kill_switch_active": bool(operations.global_kill_switch),
        "autopilot_enabled": bool(operations.autopilot_enabled),
        "real_submit_enabled": bool(settings.allow_real_application_submit),
        "greenhouse_supervised_pilot_enabled": bool(
            settings.greenhouse_supervised_pilot_enabled
        ),
    }


def _revision_blockers(runtime: Dict[str, Any]) -> list[str]:
    runtime_revision = runtime["runtime_revision"]
    expected_revision = runtime["expected_revision"]
    runtime_revision_valid = _SHA40_RE.fullmatch(runtime_revision) is not None
    expected_revision_valid = _SHA40_RE.fullmatch(expected_revision) is not None
    checks = (
        (not runtime_revision_valid, "runtime_revision_unverified"),
        (not expected_revision_valid, "expected_revision_unverified"),
        (
            runtime_revision_valid
            and expected_revision_valid
            and runtime_revision != expected_revision,
            "runtime_revision_mismatch",
        ),
    )
    return [reason for blocked, reason in checks if blocked]


def _runtime_blockers(runtime: Dict[str, Any]) -> list[str]:
    checks = (
        (runtime["runtime_mode"] != "onehost", "onehost_runtime_mode_required"),
        (
            runtime["browser_provider"] != "local",
            "playwright_owned_local_browser_required",
        ),
        (
            runtime["external_cdp_endpoint_configured"],
            "external_cdp_endpoint_must_be_empty",
        ),
        (not runtime["browser_node_id"], "onehost_browser_node_id_missing"),
        (not runtime["browser_profile_dir"], "browser_profile_dir_missing"),
        (not runtime["handoff_storage_dir"], "handoff_storage_dir_missing"),
        (not runtime["resumable_handoffs_enabled"], "resumable_handoffs_disabled"),
        (runtime["global_kill_switch_active"], "global_kill_switch_active"),
        (runtime["autopilot_enabled"], "autopilot_must_be_disabled_for_gh_oh1"),
        (
            runtime["real_submit_enabled"],
            "real_submit_flag_open_before_final_action_boundary",
        ),
        (
            runtime["greenhouse_supervised_pilot_enabled"],
            "greenhouse_pilot_flag_open_before_execution_boundary",
        ),
    )
    blockers = [reason for blocked, reason in checks if blocked]
    blockers.extend(_revision_blockers(runtime))
    return blockers


def _submission_history(
    db: Session,
    application: Application,
) -> tuple[list[SubmissionAttempt], int]:
    attempts = (
        db.query(SubmissionAttempt)
        .filter(SubmissionAttempt.application_id == application.id)
        .order_by(SubmissionAttempt.id.asc())
        .all()
    )
    evidence_count = (
        db.query(SubmissionEvidence.id)
        .filter(SubmissionEvidence.application_id == application.id)
        .count()
    )
    return attempts, int(evidence_count)


def _duplicate_state(
    application: Application,
    *,
    aliases: list[str],
    conflict: Any,
    attempts: list[SubmissionAttempt],
    evidence_count: int,
    blockers: list[str],
) -> Dict[str, Any]:
    return {
        "submission_idempotency_key_present": bool(
            _text(application.submission_idempotency_key)
        ),
        "identity_alias_count": len(aliases),
        "conflicting_application_id": (
            int(conflict.application_id) if conflict is not None else None
        ),
        "submission_attempt_count": len(attempts),
        "application_attempt_counter": int(application.submission_attempt_count or 0),
        "submission_evidence_count": evidence_count,
        "duplicate_or_replay_detected": bool(blockers),
    }


def _duplicate_defense(
    db: Session,
    application: Application,
    job: Job,
    target_metadata: Dict[str, Any],
) -> tuple[Dict[str, Any], list[str]]:
    aliases = build_submission_identity_aliases(
        job,
        application=application,
        target_metadata=target_metadata,
    )
    conflict = find_submission_identity_conflict(
        db,
        application.user_id,
        aliases,
        current_application_id=application.id,
    )
    attempts, evidence_count = _submission_history(db, application)
    duplicate_checks = (
        (conflict is not None, "duplicate_target_owned_by_another_application"),
        (
            int(application.submission_attempt_count or 0) > 0 or bool(attempts),
            "prior_submission_attempt_recorded",
        ),
        (bool(evidence_count), "prior_submission_evidence_recorded"),
    )
    blockers = [reason for blocked, reason in duplicate_checks if blocked]
    state = _duplicate_state(
        application,
        aliases=aliases,
        conflict=conflict,
        attempts=attempts,
        evidence_count=evidence_count,
        blockers=blockers,
    )
    return state, blockers


def _approval_is_stale(
    approval: SubmissionApproval,
    combined_payload_hash: str,
    application_url: str,
) -> bool:
    return (
        approval.combined_payload_hash != combined_payload_hash
        or _text(approval.application_url) != _text(application_url)
    )


def _approval_is_expired(approval: SubmissionApproval, now: datetime) -> bool:
    expires_at = _utc_naive(approval.expires_at)
    return expires_at is not None and expires_at <= now


def _approval_buckets(
    approvals: list[SubmissionApproval],
    *,
    combined_payload_hash: str,
    application_url: str,
    now: datetime,
) -> tuple[
    list[SubmissionApproval],
    list[SubmissionApproval],
    list[SubmissionApproval],
    list[SubmissionApproval],
    list[SubmissionApproval],
]:
    active = [
        item
        for item in approvals
        if item.status == SubmissionApprovalStatus.active.value
    ]
    consumed = [
        item
        for item in approvals
        if item.status == SubmissionApprovalStatus.consumed.value
    ]
    stale_active = [
        item
        for item in active
        if _approval_is_stale(item, combined_payload_hash, application_url)
    ]
    expired_active = [item for item in active if _approval_is_expired(item, now)]
    matching_active = [
        item
        for item in active
        if item not in stale_active and item not in expired_active
    ]
    return active, consumed, stale_active, expired_active, matching_active


def _approval_summary(
    approvals: list[SubmissionApproval],
    *,
    active: list[SubmissionApproval],
    consumed: list[SubmissionApproval],
    stale_active: list[SubmissionApproval],
    expired_active: list[SubmissionApproval],
    matching_active: list[SubmissionApproval],
) -> Dict[str, Any]:
    return {
        "approval_count": len(approvals),
        "active_count": len(active),
        "matching_active_count": len(matching_active),
        "consumed_count": len(consumed),
        "stale_active_count": len(stale_active),
        "expired_active_count": len(expired_active),
        "fresh_final_action_approval_present": bool(matching_active),
        "fresh_final_action_approval_required_before_final_action": True,
    }


def _approval_state(
    db: Session,
    application: Application,
    exact_payload: Dict[str, Any],
    application_url: str,
) -> tuple[Dict[str, Any], list[str]]:
    approvals = (
        db.query(SubmissionApproval)
        .filter(SubmissionApproval.application_id == application.id)
        .order_by(SubmissionApproval.created_at.asc(), SubmissionApproval.id.asc())
        .all()
    )
    buckets = _approval_buckets(
        approvals,
        combined_payload_hash=exact_payload["combined_payload_hash"],
        application_url=application_url,
        now=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    active, consumed, stale_active, expired_active, matching_active = buckets
    blocker_checks = (
        (len(active) > 1, "multiple_active_final_action_approvals"),
        (bool(stale_active), "stale_active_final_action_approval"),
        (bool(expired_active), "expired_active_final_action_approval"),
        (bool(consumed), "final_action_approval_already_consumed"),
    )
    blockers = [reason for blocked, reason in blocker_checks if blocked]
    summary = _approval_summary(
        approvals,
        active=active,
        consumed=consumed,
        stale_active=stale_active,
        expired_active=expired_active,
        matching_active=matching_active,
    )
    return summary, blockers


def _intake_blockers(
    dossier: Dict[str, Any],
    target: Dict[str, Any],
    raw_job: Dict[str, Any],
) -> list[str]:
    checks = (
        (
            target.get("platform") != "greenhouse",
            "gh_oh1_requires_greenhouse_target",
        ),
        (
            raw_job.get("selection_source") != "manual_greenhouse_phase_b",
            "canonical_greenhouse_phase_b_intake_missing",
        ),
        (
            raw_job.get("selection_policy") != "user_selected_exact_application",
            "exact_owner_selected_application_policy_missing",
        ),
        (
            not dossier["audit_state"]["event_counts"].get(
                "supervised_pilot_candidate_imported"
            ),
            "canonical_greenhouse_intake_event_missing",
        ),
    )
    return [reason for blocked, reason in checks if blocked]


def _safety_boundary() -> Dict[str, Any]:
    return {
        "read_only": True,
        "browser_started": False,
        "submission_queued": False,
        "approval_issued": False,
        "approval_consumed": False,
        "runtime_flags_changed": False,
        "final_action_authorized": False,
        "captcha_or_security_bypass_authorized": False,
        "next_boundary": (
            "supervised browser preparation, then fresh exact-payload "
            "final-action approval and revalidation"
        ),
    }


def _integrity_states(
    db: Session,
    application: Application,
    job: Job,
    target: Dict[str, Any],
    exact_payload: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any], list[str]]:
    duplicate_state, duplicate_blockers = _duplicate_defense(
        db,
        application,
        job,
        dict(target),
    )
    approval_state, approval_blockers = _approval_state(
        db,
        application,
        exact_payload,
        _text(target.get("application_url")),
    )
    blockers = [*duplicate_blockers, *approval_blockers]
    return duplicate_state, approval_state, blockers


def build_greenhouse_oh1_preflight(
    db: Session,
    application: Application,
    user: User,
    job: Job,
) -> Dict[str, Any]:
    """Return a deterministic, fail-closed GH-OH1 readiness report."""
    dossier = build_supervised_pilot_dossier(db, application, user, job)
    target = dict(dossier["target"])
    exact_payload = dict(dossier["exact_payload"])
    runtime = _runtime_contract()
    blockers = _intake_blockers(dossier, target, dict(job.raw_data or {}))
    blockers.extend(dossier["preflight"]["structural_blockers"])
    blockers.extend(_runtime_blockers(runtime))
    duplicate_state, approval_state, integrity_blockers = _integrity_states(
        db,
        application,
        job,
        target,
        exact_payload,
    )
    blockers.extend(integrity_blockers)
    blockers = list(dict.fromkeys(_text(item) for item in blockers if _text(item)))
    return {
        "preflight_version": PREFLIGHT_VERSION,
        "status": READY_STATUS if not blockers else BLOCKED_STATUS,
        "ready": not blockers,
        "application_id": application.id,
        "blockers": blockers,
        "target": target,
        "exact_payload": exact_payload,
        "dossier_sha256": dossier["dossier_sha256"],
        "structural_preflight": dict(dossier["preflight"]),
        "runtime_contract": runtime,
        "duplicate_defense": duplicate_state,
        "approval_state": approval_state,
        "safety_boundary": _safety_boundary(),
    }


__all__ = [
    "BLOCKED_STATUS",
    "PREFLIGHT_VERSION",
    "READY_STATUS",
    "build_greenhouse_oh1_preflight",
]
