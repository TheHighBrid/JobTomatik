"""Fail-closed provenance validation for full-stack shadow certification evidence.

A certification evidence row is only a claim. Shadow-run evidence becomes trustworthy
only when it can be traced back to exactly one completed, account-owned
``ShadowRunSession`` whose retained final report still hashes to the recorded report
identity and still proves the no-submit/reconciliation qualification gates.

This module intentionally does not import ``certification_scale`` so the release
evaluator can call it without creating a service import cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.models.certification import CertificationEvidence, ShadowRunSession


SHADOW_EVIDENCE_TYPES = {
    "shadow_run_4h",
    "shadow_run_8h",
    "shadow_run_24h",
}


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_false(value: Any) -> bool:
    return value is False


def _is_true(value: Any) -> bool:
    return value is True


def shadow_evidence_provenance_reasons(
    db: Session,
    record: CertificationEvidence,
    *,
    expected_user_id: int | None,
    canonical_hash: Callable[[Any], str],
) -> list[str]:
    """Return deterministic blockers for one shadow certification evidence record.

    The validator re-opens the retained campaign instead of trusting copied evidence
    metadata. This makes verification and release qualification resilient to legacy
    hand-written timer records and to post-recording drift in the campaign/report.
    """

    if record.evidence_type not in SHADOW_EVIDENCE_TYPES:
        return []

    reasons: list[str] = []
    metadata = dict(record.evidence_metadata or {})

    if record.recorded_by_user_id is None:
        reasons.append("shadow_evidence_must_be_user_owned")
    if expected_user_id is not None and record.recorded_by_user_id != expected_user_id:
        reasons.append("shadow_evidence_owner_mismatch")
    if record.environment != "full-stack-shadow":
        reasons.append("shadow_provenance_environment_mismatch")
    if metadata.get("full_stack_shadow_session") is not True:
        reasons.append("shadow_full_stack_provenance_missing")

    session_id = _as_int(metadata.get("session_id"))
    if session_id is None or session_id <= 0:
        reasons.append("shadow_session_id_missing")
        return reasons

    session = (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.id == session_id)
        .first()
    )
    if session is None:
        reasons.append("shadow_session_missing")
        return reasons

    if record.recorded_by_user_id != session.user_id:
        reasons.append("shadow_session_owner_mismatch")
    if expected_user_id is not None and session.user_id != expected_user_id:
        reasons.append("shadow_session_expected_owner_mismatch")
    if session.status != "completed":
        reasons.append("shadow_session_not_completed")
    if session.target_evidence_type != record.evidence_type:
        reasons.append("shadow_session_target_mismatch")
    if str(session.candidate_revision or "").lower() != str(record.commit_sha or "").lower():
        reasons.append("shadow_session_revision_mismatch")
    if session.certification_evidence_id != record.id:
        reasons.append("shadow_session_evidence_link_mismatch")

    linked_count = (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.certification_evidence_id == record.id)
        .count()
    )
    if linked_count != 1:
        reasons.append("shadow_session_evidence_link_not_unique")

    requirement_seconds = {
        "shadow_run_4h": 4 * 60 * 60,
        "shadow_run_8h": 8 * 60 * 60,
        "shadow_run_24h": 24 * 60 * 60,
    }[record.evidence_type]
    if int(session.requested_duration_seconds or 0) != requirement_seconds:
        reasons.append("shadow_requested_duration_mismatch")
    if int(session.cycles_completed or 0) <= 0:
        reasons.append("shadow_cycle_count_missing")
    if int(session.cycles_failed or 0) != 0:
        reasons.append("shadow_cycle_failure_present")
    if session.final_submit_allowed is not False:
        reasons.append("shadow_session_submit_flag_changed")

    report = dict(session.final_report or {})
    report_hash = str(session.report_sha256 or "")
    metadata_hash = str(metadata.get("report_sha256") or "")
    if not report or not report_hash:
        reasons.append("shadow_report_missing")
        return reasons

    report_without_hash = dict(report)
    embedded_hash = str(report_without_hash.pop("report_sha256", ""))
    recomputed_hash = canonical_hash(report_without_hash)
    if not embedded_hash or embedded_hash != recomputed_hash:
        reasons.append("shadow_report_hash_mismatch")
    if report_hash != embedded_hash or metadata_hash != embedded_hash:
        reasons.append("shadow_report_identity_mismatch")

    if _as_int(report.get("session_id")) != session.id:
        reasons.append("shadow_report_session_mismatch")
    if report.get("status") != "completed":
        reasons.append("shadow_report_status_mismatch")
    if str(report.get("candidate_revision") or "").lower() != str(session.candidate_revision or "").lower():
        reasons.append("shadow_report_revision_mismatch")
    if report.get("target_evidence_type") != session.target_evidence_type:
        reasons.append("shadow_report_target_mismatch")
    if report.get("qualification_eligible") is not True:
        reasons.append("shadow_report_not_qualifying")

    measured = _as_int(float(report.get("measured_duration_seconds") or 0))
    if measured is None or measured != int(record.duration_seconds or 0):
        reasons.append("shadow_duration_mismatch")
    if measured is None or measured < requirement_seconds:
        reasons.append("shadow_duration_below_required_minimum")

    reconciliation = dict(report.get("reconciliation") or {})
    if reconciliation.get("reconciled") is not True:
        reasons.append("shadow_report_reconciliation_failed")

    quality = dict(report.get("quality") or {})
    required_quality = {
        "duration_satisfied",
        "scheduler_cycles_completed",
        "no_cycle_failures",
        "discovery_path_observed",
        "application_path_observed",
        "no_leaked_or_missing_application_records",
        "no_duplicate_scheduler_application_references",
        "no_false_submitted_status",
        "no_runaway_retry",
        "no_unexplained_failures",
        "no_policy_escape",
        "no_active_application_work",
    }
    if any(quality.get(name) is not True for name in required_quality):
        reasons.append("shadow_report_quality_gate_failed")

    safety = dict(report.get("safety") or {})
    if not (
        _is_false(safety.get("final_submit_enabled"))
        and _is_false(safety.get("final_submit_clicked"))
        and _is_true(safety.get("real_submission_remained_disabled"))
        and _is_true(safety.get("dry_run_required"))
        and _is_false(safety.get("runtime_settings_changed_by_supervisor"))
        and _is_false(safety.get("submission_authorized"))
        and _is_false(safety.get("outreach_authorized"))
    ):
        reasons.append("shadow_report_safety_failed")

    copied_invariants = {
        "measured_elapsed_time": True,
        "final_submit_enabled": False,
        "final_submit_clicked": False,
        "real_submission_remained_disabled": True,
        "qualification_eligible": True,
        "reconciled": True,
        "submission_authorized": False,
        "outreach_authorized": False,
    }
    if any(metadata.get(key) is not expected for key, expected in copied_invariants.items()):
        reasons.append("shadow_evidence_metadata_drift")
    if _as_int(metadata.get("cycles_completed")) != int(session.cycles_completed or 0):
        reasons.append("shadow_evidence_cycle_count_drift")
    if _as_int(metadata.get("cycles_failed")) != int(session.cycles_failed or 0):
        reasons.append("shadow_evidence_cycle_failure_drift")

    expected_reference = f"full-stack-shadow-session:{session.id}:{report_hash}"
    if record.source_reference != expected_reference:
        reasons.append("shadow_source_reference_mismatch")

    return list(dict.fromkeys(reasons))


__all__ = [
    "SHADOW_EVIDENCE_TYPES",
    "shadow_evidence_provenance_reasons",
]
