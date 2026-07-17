"""Independent review and pilot-ledger export for submission evidence.

This service never opens a browser or submits an application. It verifies a
retained evidence record against an immutable snapshot, requires explicit human
confirmations, and only then promotes a runtime application from ``submitted``
or ``submission_uncertain`` to ``confirmed``. Rejected evidence fails closed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewReason,
    SubmissionEvidence,
)
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.submission_evidence_review import (
    SubmissionEvidenceReview,
    SubmissionEvidenceReviewDecision,
)
from app.models.user import User
from app.services.application_state import (
    create_manual_review_task,
    normalize_state,
    transition_application_state,
)


ACCEPTED = SubmissionEvidenceReviewDecision.accepted.value
REJECTED = SubmissionEvidenceReviewDecision.rejected.value
STRONG_EVIDENCE_TYPES = {
    "confirmation_page",
    "success_banner",
    "external_application_id",
    "portal_history",
    "confirmation_email",
    "email_provider_receipt",
}


class SubmissionEvidenceReviewError(ValueError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text_hash(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_evidence_snapshot(evidence: SubmissionEvidence) -> Dict[str, Any]:
    """Return a review-safe immutable snapshot without raw confirmation text."""

    safe_metadata = dict(evidence.evidence_metadata or {})
    for key in list(safe_metadata):
        lowered = str(key).lower()
        if any(token in lowered for token in ("password", "token", "cookie", "secret", "answer")):
            safe_metadata.pop(key, None)

    payload = {
        "evidence_id": evidence.id,
        "application_id": evidence.application_id,
        "evidence_type": evidence.evidence_type,
        "is_sufficient": bool(evidence.is_sufficient),
        "final_url": evidence.final_url,
        "confirmation_text_hash": _text_hash(evidence.confirmation_text),
        "confirmation_text_present": bool((evidence.confirmation_text or "").strip()),
        "selector": evidence.selector,
        "external_application_id": evidence.external_application_id,
        "screenshot_path": evidence.screenshot_path,
        "html_snapshot_path": evidence.html_snapshot_path,
        "payload_hash": evidence.payload_hash,
        "evidence_metadata": safe_metadata,
        "captured_at": evidence.captured_at.isoformat() if evidence.captured_at else None,
    }
    return {**payload, "evidence_snapshot_hash": _hash_value(payload)}


def _latest_consumed_approval(db: Session, application_id: int) -> Optional[SubmissionApproval]:
    return (
        db.query(SubmissionApproval)
        .filter(
            SubmissionApproval.application_id == application_id,
            SubmissionApproval.status == SubmissionApprovalStatus.consumed.value,
        )
        .order_by(SubmissionApproval.consumed_at.desc(), SubmissionApproval.id.desc())
        .first()
    )


def _concrete_signal_present(snapshot: Mapping[str, Any]) -> bool:
    if snapshot.get("evidence_type") not in STRONG_EVIDENCE_TYPES:
        return False
    return bool(
        snapshot.get("confirmation_text_present")
        or snapshot.get("external_application_id")
        or snapshot.get("screenshot_path")
        or snapshot.get("html_snapshot_path")
    )


def build_evidence_review_preflight(
    db: Session,
    application: Application,
    job: Job,
    evidence: SubmissionEvidence,
) -> Dict[str, Any]:
    snapshot = build_evidence_snapshot(evidence)
    approval = _latest_consumed_approval(db, application.id)
    state = normalize_state(application.automation_state)
    blockers = []

    if evidence.application_id != application.id:
        blockers.append("evidence_application_mismatch")
    if state not in {
        ApplicationAutomationState.submitted.value,
        ApplicationAutomationState.submission_uncertain.value,
        ApplicationAutomationState.confirmed.value,
    }:
        blockers.append("application_not_waiting_for_evidence_review")
    if not evidence.is_sufficient:
        blockers.append("evidence_not_marked_sufficient")
    if not _concrete_signal_present(snapshot):
        blockers.append("concrete_confirmation_signal_missing")
    if not approval:
        blockers.append("consumed_supervised_approval_missing")

    existing = (
        db.query(SubmissionEvidenceReview)
        .filter(
            SubmissionEvidenceReview.evidence_id == evidence.id,
            SubmissionEvidenceReview.evidence_snapshot_hash == snapshot["evidence_snapshot_hash"],
        )
        .order_by(SubmissionEvidenceReview.id.desc())
        .first()
    )

    return {
        "ready_for_acceptance": not blockers,
        "blockers": blockers,
        "application_id": application.id,
        "application_state": state,
        "employer": str(job.company or "").strip(),
        "role": str(job.title or "").strip(),
        "application_url": str(job.url or "").strip(),
        "submission_idempotency_key": application.submission_idempotency_key,
        "evidence": snapshot,
        "approval_reference": approval.reference if approval else None,
        "application_payload_hash": approval.combined_payload_hash if approval else None,
        "existing_review": serialize_evidence_review(existing, current_snapshot=snapshot) if existing else None,
    }


def serialize_evidence_review(
    review: SubmissionEvidenceReview,
    *,
    current_snapshot: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    current_hash = (
        str(current_snapshot.get("evidence_snapshot_hash"))
        if current_snapshot is not None
        else review.evidence_snapshot_hash
    )
    return {
        "id": review.id,
        "reference": review.reference,
        "application_id": review.application_id,
        "evidence_id": review.evidence_id,
        "reviewer_user_id": review.reviewer_user_id,
        "approval_reference": review.approval_reference,
        "decision": review.decision,
        "evidence_snapshot_hash": review.evidence_snapshot_hash,
        "application_payload_hash": review.application_payload_hash,
        "review_notes": review.review_notes,
        "review_metadata": dict(review.review_metadata or {}),
        "reviewed_at": review.reviewed_at.isoformat() if review.reviewed_at else None,
        "valid_for_current_evidence": review.evidence_snapshot_hash == current_hash,
    }


def review_submission_evidence(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    evidence: SubmissionEvidence,
    *,
    decision: str,
    confirm_employer: str,
    confirm_role: str,
    confirm_evidence_type: str,
    confirm_evidence_matches_application: bool,
    review_acknowledgement: str,
    notes: Optional[str] = None,
) -> SubmissionEvidenceReview:
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in {ACCEPTED, REJECTED}:
        raise SubmissionEvidenceReviewError("decision must be accepted or rejected")
    if confirm_evidence_matches_application is not True:
        raise SubmissionEvidenceReviewError(
            "confirm_evidence_matches_application must be explicitly true"
        )
    if review_acknowledgement.strip() != "REVIEWED":
        raise SubmissionEvidenceReviewError(
            "review_acknowledgement must exactly equal REVIEWED"
        )

    preflight = build_evidence_review_preflight(db, application, job, evidence)
    confirmations = {
        "employer": (confirm_employer.strip(), preflight["employer"]),
        "role": (confirm_role.strip(), preflight["role"]),
        "evidence_type": (
            confirm_evidence_type.strip(),
            preflight["evidence"]["evidence_type"],
        ),
    }
    mismatches = [
        field
        for field, (provided, expected) in confirmations.items()
        if provided != expected
    ]
    if mismatches:
        raise SubmissionEvidenceReviewError(
            "Explicit evidence confirmation did not match: " + ", ".join(mismatches)
        )
    if normalized_decision == ACCEPTED and not preflight["ready_for_acceptance"]:
        raise SubmissionEvidenceReviewError(
            "Evidence acceptance is blocked: " + ", ".join(preflight["blockers"])
        )

    snapshot_hash = preflight["evidence"]["evidence_snapshot_hash"]
    existing = (
        db.query(SubmissionEvidenceReview)
        .filter(
            SubmissionEvidenceReview.evidence_id == evidence.id,
            SubmissionEvidenceReview.evidence_snapshot_hash == snapshot_hash,
        )
        .first()
    )
    if existing:
        if existing.decision != normalized_decision:
            raise SubmissionEvidenceReviewError(
                "This exact evidence snapshot already has a conflicting review"
            )
        return existing

    review = SubmissionEvidenceReview(
        application_id=application.id,
        evidence_id=evidence.id,
        reviewer_user_id=user.id,
        approval_reference=preflight["approval_reference"],
        decision=normalized_decision,
        evidence_snapshot_hash=snapshot_hash,
        application_payload_hash=preflight["application_payload_hash"],
        review_notes=notes,
        review_metadata={
            "review_source": "authenticated_user_independent_evidence_review",
            "confirm_evidence_matches_application": True,
            "evidence_type": evidence.evidence_type,
            "confirmation_text_hash": preflight["evidence"]["confirmation_text_hash"],
            "external_application_id_present": bool(evidence.external_application_id),
            "screenshot_present": bool(evidence.screenshot_path),
            "html_snapshot_present": bool(evidence.html_snapshot_path),
        },
    )
    db.add(review)
    db.flush()

    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="submission_evidence_reviewed",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                "review_reference": review.reference,
                "evidence_id": evidence.id,
                "decision": normalized_decision,
                "evidence_snapshot_hash": snapshot_hash,
                "approval_reference": review.approval_reference,
            },
        )
    )

    if normalized_decision == ACCEPTED:
        if normalize_state(application.automation_state) != ApplicationAutomationState.confirmed.value:
            transition_application_state(
                db,
                application,
                ApplicationAutomationState.confirmed,
                "submission_evidence_independently_confirmed",
                {
                    "review_reference": review.reference,
                    "evidence_id": evidence.id,
                    "approval_reference": review.approval_reference,
                },
            )
        application.status = ApplicationStatus.applied
        db.add(
            Notification(
                user_id=user.id,
                type=NotificationType.system,
                title=f"Submission evidence confirmed: {job.title}",
                message="Concrete submission evidence passed the independent review gate.",
                data={
                    "application_id": application.id,
                    "evidence_id": evidence.id,
                    "review_reference": review.reference,
                },
            )
        )
    else:
        if normalize_state(application.automation_state) != ApplicationAutomationState.confirmed.value:
            create_manual_review_task(
                db,
                application,
                ManualReviewReason.submission_confirmation_uncertain,
                "Retained submission evidence was rejected during independent review.",
                details={
                    "evidence_id": evidence.id,
                    "review_reference": review.reference,
                    "evidence_snapshot_hash": snapshot_hash,
                },
                blocking_url=evidence.final_url or job.url,
                target_state=ApplicationAutomationState.submission_uncertain,
            )
        db.add(
            Notification(
                user_id=user.id,
                type=NotificationType.system,
                title=f"Submission evidence rejected: {job.title}",
                message="The application remains unconfirmed and requires manual review.",
                data={
                    "application_id": application.id,
                    "evidence_id": evidence.id,
                    "review_reference": review.reference,
                },
            )
        )

    return review


def build_supervised_pilot_record(
    db: Session,
    application: Application,
    user: User,
    job: Job,
) -> Dict[str, Any]:
    """Export one confirmed runtime application into the canonical pilot shape."""

    if normalize_state(application.automation_state) != ApplicationAutomationState.confirmed.value:
        raise SubmissionEvidenceReviewError("Application is not independently confirmed")

    reviews = (
        db.query(SubmissionEvidenceReview)
        .filter(
            SubmissionEvidenceReview.application_id == application.id,
            SubmissionEvidenceReview.decision == ACCEPTED,
        )
        .order_by(SubmissionEvidenceReview.reviewed_at.desc(), SubmissionEvidenceReview.id.desc())
        .all()
    )
    selected_review: Optional[SubmissionEvidenceReview] = None
    selected_evidence: Optional[SubmissionEvidence] = None
    for candidate in reviews:
        evidence = db.query(SubmissionEvidence).filter(SubmissionEvidence.id == candidate.evidence_id).first()
        if not evidence:
            continue
        snapshot = build_evidence_snapshot(evidence)
        if candidate.evidence_snapshot_hash == snapshot["evidence_snapshot_hash"]:
            selected_review = candidate
            selected_evidence = evidence
            break
    if not selected_review or not selected_evidence:
        raise SubmissionEvidenceReviewError(
            "No accepted review remains valid for the current evidence snapshot"
        )

    approval = (
        db.query(SubmissionApproval)
        .filter(SubmissionApproval.reference == selected_review.approval_reference)
        .first()
    )
    if not approval or approval.status != SubmissionApprovalStatus.consumed.value:
        raise SubmissionEvidenceReviewError("Consumed supervised approval evidence is missing")

    run_seed = {
        "application_id": application.id,
        "approval_reference": approval.reference,
        "review_reference": selected_review.reference,
        "evidence_snapshot_hash": selected_review.evidence_snapshot_hash,
    }
    run_id = "gh-supervised-" + _hash_value(run_seed)[:20]
    evidence_reference = (
        f"submission-evidence:{selected_evidence.id}:review:{selected_review.reference}"
    )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "mode": "supervised_real_submission",
        "started_at": application.last_submission_attempt_at.isoformat()
        if application.last_submission_attempt_at
        else None,
        "completed_at": selected_review.reviewed_at.isoformat()
        if selected_review.reviewed_at
        else datetime.utcnow().isoformat(),
        "employer": str(job.company or "").strip() or None,
        "role": str(job.title or "").strip() or None,
        "board_token": None,
        "job_id": str(job.external_id or job.id),
        "application_url": approval.application_url,
        "adapter": "greenhouse",
        "adapter_version": None,
        "framework_version": None,
        "operator": f"user:{user.id}",
        "source_reference": f"runtime-application:{application.id}",
        "approval_reference": approval.reference,
        "profile_snapshot_hash": approval.profile_snapshot_hash,
        "resume_hash": approval.resume_hash,
        "cover_letter_hash": approval.cover_letter_hash,
        "answer_payload_hash": approval.answer_payload_hash,
        "controls_discovered": None,
        "controls_filled": None,
        "controls_skipped": None,
        "controls_blocked": 0,
        "policies_used": int((approval.approval_metadata or {}).get("policy_count") or 0),
        "uploads_verified": 1,
        "validation_errors": [],
        "handoff_reason": None,
        "handoff_boundary": None,
        "pre_submit_state": "ready_to_submit",
        "final_url": selected_evidence.final_url or approval.application_url,
        "final_submit_clicked": True,
        "confirmation_evidence_type": selected_evidence.evidence_type,
        "confirmation_evidence_reference": evidence_reference,
        "final_status": "confirmed",
        "duplicate_guard_verified": bool(application.submission_idempotency_key),
        "duplicate_submission_detected": False,
        "reviewed_by": f"user:{selected_review.reviewer_user_id}",
        "review_reference": selected_review.reference,
        "qualifies_for_dry_run_matrix": False,
        "synthetic_profile": False,
        "error": None,
        "notes": selected_review.review_notes,
    }


__all__ = [
    "SubmissionEvidenceReviewError",
    "build_evidence_review_preflight",
    "build_evidence_snapshot",
    "build_supervised_pilot_record",
    "review_submission_evidence",
    "serialize_evidence_review",
]
