"""Sanitized, deterministic review dossier for one Greenhouse Phase B candidate.

The dossier is read-only. It never ranks or selects a job, copies raw applicant
answers, issues an approval, enables a feature flag, opens a browser, or queues a
submission. Its SHA-256 digest changes when the exact payload or retained safety
evidence changes, giving the operator one stable object to review before using the
separate exact-approval flow.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationEvent,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.submission_evidence_review import SubmissionEvidenceReview
from app.models.user import User
from app.services.supervised_pilot_roster import EXECUTION_FLAG_BLOCKERS
from app.services.supervised_submission import build_supervised_preflight


DOSSIER_VERSION = "1.0.0"
MANDATORY_STOP_REASONS = [
    "captcha_detected",
    "anti_bot_challenge",
    "mfa_required",
    "login_required",
    "assessment_required",
    "identity_verification_required",
    "ambiguous_legal_or_consent_boundary",
]


class SupervisedPilotDossierError(ValueError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _host(value: Optional[str]) -> Optional[str]:
    return (urlparse(value or "").hostname or "").lower() or None


def _pilot_progress(readiness: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    payload = dict(readiness or {})
    summary = dict(payload.get("summary") or {})
    dry_runs = int(summary.get("qualifying_dry_run_count") or 0)
    employers = int(summary.get("distinct_dry_run_employer_count") or 0)
    confirmed = int(summary.get("supervised_confirmed_count") or 0)
    return {
        "phase_a_qualifying_dry_runs": dry_runs,
        "phase_a_distinct_employers": employers,
        "phase_a_complete": dry_runs >= 30 and employers >= 30,
        "phase_b_confirmed_records": confirmed,
        "phase_b_target": 10,
        "phase_b_remaining": max(0, 10 - confirmed),
        "phase_b_complete": confirmed >= 10,
        "readiness_available": bool(summary),
    }


def build_supervised_pilot_dossier(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    readiness: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one deterministic dossier without mutating application state."""

    preflight = build_supervised_preflight(db, application, user, job)
    if preflight["platform"] != "greenhouse":
        raise SupervisedPilotDossierError(
            "Phase B dossiers are available only for Greenhouse applications"
        )

    manual_reviews = (
        db.query(ManualReviewTask)
        .filter(ManualReviewTask.application_id == application.id)
        .order_by(ManualReviewTask.created_at.asc(), ManualReviewTask.id.asc())
        .all()
    )
    approvals = (
        db.query(SubmissionApproval)
        .filter(SubmissionApproval.application_id == application.id)
        .order_by(SubmissionApproval.created_at.asc(), SubmissionApproval.id.asc())
        .all()
    )
    evidence_rows = (
        db.query(SubmissionEvidence)
        .filter(SubmissionEvidence.application_id == application.id)
        .order_by(SubmissionEvidence.captured_at.asc(), SubmissionEvidence.id.asc())
        .all()
    )
    evidence_reviews = (
        db.query(SubmissionEvidenceReview)
        .filter(SubmissionEvidenceReview.application_id == application.id)
        .order_by(
            SubmissionEvidenceReview.reviewed_at.asc(),
            SubmissionEvidenceReview.id.asc(),
        )
        .all()
    )
    events = (
        db.query(ApplicationEvent)
        .filter(ApplicationEvent.application_id == application.id)
        .order_by(ApplicationEvent.created_at.asc(), ApplicationEvent.id.asc())
        .all()
    )

    structural_blockers = [
        blocker
        for blocker in preflight["blockers"]
        if blocker not in EXECUTION_FLAG_BLOCKERS
    ]
    open_review_reasons = sorted(
        {
            item.reason_code
            for item in manual_reviews
            if item.status
            in {ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value}
        }
    )
    event_counts = dict(sorted(Counter(item.event_type for item in events).items()))

    dossier: Dict[str, Any] = {
        "snapshot_version": DOSSIER_VERSION,
        "scope": "greenhouse_supervised_phase_b_candidate",
        "selection_policy": "user_selected_exact_application_no_ranking",
        "read_only": True,
        "application_id": application.id,
        "target": {
            "employer": preflight["employer"],
            "role": preflight["role"],
            "application_url": preflight["application_url"],
            "application_host": _host(preflight["application_url"]),
            "platform": preflight["platform"],
        },
        "application_state": {
            "status": str(getattr(application.status, "value", application.status)),
            "automation_state": preflight["automation_state"],
            "submission_attempt_count": int(application.submission_attempt_count or 0),
            "last_submission_attempt_at": _iso(application.last_submission_attempt_at),
            "created_at": _iso(application.created_at),
            "updated_at": _iso(application.updated_at),
            "submission_idempotency_key": preflight["submission_idempotency_key"],
            "duplicate_prevention_key_present": bool(
                preflight["submission_idempotency_key"]
            ),
        },
        "exact_payload": {
            "profile_snapshot_hash": preflight["profile_snapshot_hash"],
            "resume_hash": preflight["resume_hash"],
            "cover_letter_hash": preflight["cover_letter_hash"],
            "answer_payload_hash": preflight["answer_payload_hash"],
            "combined_payload_hash": preflight["combined_payload_hash"],
            "resume_filename": preflight["resume_filename"],
            "cover_letter_present": preflight["cover_letter_present"],
            "approved_answer_policy_count": preflight["policy_count"],
            "raw_profile_values_included": False,
            "raw_answer_values_included": False,
            "raw_cover_letter_included": False,
        },
        "preflight": {
            "technical_ready": not structural_blockers,
            "execution_ready": bool(preflight["ready"]),
            "structural_blockers": structural_blockers,
            "execution_blockers": list(preflight["blockers"]),
            "unresolved_manual_review_count": preflight[
                "unresolved_manual_review_count"
            ],
            "open_manual_review_reasons": open_review_reasons,
        },
        "kill_switches": {
            "global_flag_name": "ALLOW_REAL_APPLICATION_SUBMIT",
            "global_flag_enabled": preflight["global_live_submit_enabled"],
            "platform_flag_name": "GREENHOUSE_SUPERVISED_PILOT_ENABLED",
            "platform_flag_enabled": preflight["platform_pilot_enabled"],
            "one_time_approval_required": True,
            "approval_can_be_revoked": True,
            "direct_submit_action_in_dossier": False,
        },
        "mandatory_handoff_boundaries": {
            "bypass_forbidden": True,
            "stop_reasons": MANDATORY_STOP_REASONS,
        },
        "manual_review_state": {
            "total_count": len(manual_reviews),
            "open_or_in_progress_count": preflight[
                "unresolved_manual_review_count"
            ],
            "reason_statuses": [
                {
                    "reason_code": item.reason_code,
                    "status": item.status,
                    "created_at": _iso(item.created_at),
                    "expires_at": _iso(item.expires_at),
                }
                for item in manual_reviews
            ],
        },
        "approval_state": {
            "count": len(approvals),
            "records": [
                {
                    "reference": item.reference,
                    "status": item.status,
                    "combined_payload_hash": item.combined_payload_hash,
                    "approved_at": _iso(item.approved_at),
                    "expires_at": _iso(item.expires_at),
                    "consumed_at": _iso(item.consumed_at),
                    "revoked_at": _iso(item.revoked_at),
                }
                for item in approvals
            ],
        },
        "submission_evidence_state": {
            "count": len(evidence_rows),
            "sufficient_count": sum(1 for item in evidence_rows if item.is_sufficient),
            "records": [
                {
                    "evidence_id": item.id,
                    "evidence_type": item.evidence_type,
                    "is_sufficient": bool(item.is_sufficient),
                    "payload_hash": item.payload_hash,
                    "final_url_host": _host(item.final_url),
                    "external_application_id_present": bool(
                        item.external_application_id
                    ),
                    "screenshot_retained": bool(item.screenshot_path),
                    "html_snapshot_retained": bool(item.html_snapshot_path),
                    "captured_at": _iso(item.captured_at),
                }
                for item in evidence_rows
            ],
        },
        "independent_review_state": {
            "count": len(evidence_reviews),
            "accepted_count": sum(
                1 for item in evidence_reviews if item.decision == "accepted"
            ),
            "records": [
                {
                    "reference": item.reference,
                    "evidence_id": item.evidence_id,
                    "decision": item.decision,
                    "approval_reference": item.approval_reference,
                    "evidence_snapshot_hash": item.evidence_snapshot_hash,
                    "application_payload_hash": item.application_payload_hash,
                    "reviewed_at": _iso(item.reviewed_at),
                }
                for item in evidence_reviews
            ],
        },
        "audit_state": {
            "event_count": len(events),
            "event_counts": event_counts,
            "latest_event_at": _iso(events[-1].created_at) if events else None,
            "pilot_record_ingested": bool(
                event_counts.get("supervised_pilot_record_ingested")
            ),
        },
        "pilot_progress": _pilot_progress(readiness),
    }

    dossier["dossier_sha256"] = _sha256(dossier)
    dossier["download_filename"] = (
        f"greenhouse-phase-b-dossier-application-{application.id}.json"
    )
    return dossier


__all__ = [
    "DOSSIER_VERSION",
    "SupervisedPilotDossierError",
    "build_supervised_pilot_dossier",
]
