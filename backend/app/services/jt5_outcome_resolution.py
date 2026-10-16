"""Audited owner resolution of uncertain JT5 attempts without automatic replay.

Confirmation uses retained sufficient evidence. Non-submission is an explicit
owner finding supported by an employer response or portal verification; silence,
a missing receipt, and rejected confirmation evidence do not prove non-submission.
No browser, employer request, approval, queue publication, or release flag change
is performed here. The sole worker must be idle before releasing a retry block.
"""

import hashlib
import json
from datetime import datetime, timezone

from app.models.application import (
    Application, ApplicationStatus,
    ManualReviewStatus, ManualReviewTask, SubmissionEvidence,
)
from app.models.handoff import ACTIVE_HANDOFF_STATUSES, ManualHandoffSession
from app.models.submission_integrity import SubmissionAttempt
from app.models.submission_evidence_review import SubmissionEvidenceReview
from app.services.application_attempt_lifecycle_jt5 import complete_jt5_attempt
from app.services.application_state import normalize_state, transition_application_state
from app.services.submission_evidence_review import STRONG_EVIDENCE_TYPES, build_evidence_snapshot


class JT5ResolutionError(ValueError):
    pass


def require_idle_onehost_worker():
    """Fail closed when the sole worker is busy, missing, or cannot be inspected."""
    from app.celery_app import celery_app

    try:
        inspector = celery_app.control.inspect(timeout=2)
        active = inspector.active()
        reserved = inspector.reserved()
        scheduled = inspector.scheduled()
    except Exception as exc:
        raise JT5ResolutionError("Worker state is unavailable; retry remains blocked") from exc
    snapshots = (active, reserved, scheduled)
    if any(not isinstance(value, dict) or len(value) != 1 for value in snapshots):
        raise JT5ResolutionError("Recovery requires one reachable OneHost worker")
    if not all(set(value) == set(active) for value in snapshots):
        raise JT5ResolutionError("Worker identity changed during inspection")
    if any(tasks for value in snapshots for tasks in value.values()):
        raise JT5ResolutionError("The worker is busy; finish the active work before resolving non-submission")


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _confirmation_snapshot(evidence, attempt):
    if not evidence.is_sufficient or evidence.evidence_type not in STRONG_EVIDENCE_TYPES:
        raise JT5ResolutionError("Retained sufficient confirmation evidence is required")
    if not any((evidence.confirmation_text, evidence.external_application_id,
                evidence.screenshot_path, evidence.html_snapshot_path)):
        raise JT5ResolutionError("The evidence has no concrete confirmation signal")
    if not evidence.captured_at or _utc(evidence.captured_at) < _utc(attempt.queued_at):
        raise JT5ResolutionError("The evidence predates this attempt")
    bound = (evidence.evidence_metadata or {}).get("attempt_reference")
    if bound and bound != attempt.reference:
        raise JT5ResolutionError("The evidence belongs to a different attempt")
    return build_evidence_snapshot(evidence)


def _pending_resolution(attempt):
    metadata = attempt.attempt_metadata or {}
    return metadata.get("execution_contract") == "jt5" and (
        attempt.status == "uncertain"
        or (attempt.status == "queued" and metadata.get("dispatch_status") == "reconciliation_required")
    )


def resolution_context(db, application):
    """Read-only recovery context; does not inspect or contact the browser/worker."""
    attempt = db.query(SubmissionAttempt).filter(
        SubmissionAttempt.application_id == application.id,
    ).order_by(SubmissionAttempt.id.desc()).first()
    options = []
    if attempt and _pending_resolution(attempt):
        for evidence in db.query(SubmissionEvidence).filter(
            SubmissionEvidence.application_id == application.id,
        ).order_by(SubmissionEvidence.id.desc()).all():
            try:
                snapshot = _confirmation_snapshot(evidence, attempt)
            except JT5ResolutionError:
                continue
            options.append({
                "id": evidence.id, "evidence_type": evidence.evidence_type,
                "snapshot_hash": snapshot["evidence_snapshot_hash"],
                "confirmation_text": evidence.confirmation_text,
                "final_url": evidence.final_url,
                "external_application_id": evidence.external_application_id,
            })
    return {
        "attempt_reference": attempt.reference if attempt else None,
        "resolution_required": bool(attempt and _pending_resolution(attempt)),
        "confirmation_evidence": options,
        "resolution": (attempt.attempt_metadata or {}).get("owner_resolution") if attempt else None,
        "automatic_retry_allowed": False,
    }


def _verify_confirmation(db, application, attempt, data):
    if data.evidence_source != "retained_confirmation" or not data.evidence_id:
        raise JT5ResolutionError("Select retained confirmation evidence for this application")
    evidence = db.query(SubmissionEvidence).filter(
        SubmissionEvidence.id == data.evidence_id,
        SubmissionEvidence.application_id == application.id,
    ).with_for_update().populate_existing().first()
    if evidence is None:
        raise JT5ResolutionError("Confirmation evidence was not found for this application")
    snapshot = _confirmation_snapshot(evidence, attempt)
    if data.evidence_snapshot_hash != snapshot["evidence_snapshot_hash"]:
        raise JT5ResolutionError("The evidence changed; reload it before recording a decision")
    if db.query(SubmissionEvidenceReview.id).filter(
        SubmissionEvidenceReview.evidence_id == evidence.id,
        SubmissionEvidenceReview.evidence_snapshot_hash == snapshot["evidence_snapshot_hash"],
        SubmissionEvidenceReview.decision == "rejected",
    ).first():
        raise JT5ResolutionError("This confirmation evidence was rejected during review")
    return snapshot


def _verify_non_submission(db, application, attempt, data):
    if data.evidence_source not in {"employer_response", "employer_portal"}:
        raise JT5ResolutionError("Non-submission requires an authoritative employer response or portal verification")
    if data.evidence_id is not None or data.evidence_snapshot_hash is not None:
        raise JT5ResolutionError("Confirmation evidence cannot establish non-submission")
    if application.status not in {ApplicationStatus.pending, ApplicationStatus.applying}:
        raise JT5ResolutionError("Recorded application history must not be reset by recovery")
    if db.query(SubmissionEvidence.id).filter(
        SubmissionEvidence.application_id == application.id,
        SubmissionEvidence.is_sufficient.is_(True),
    ).first():
        raise JT5ResolutionError("Existing sufficient submission evidence conflicts with non-submission")
    if db.query(ManualHandoffSession.id).filter(
        ManualHandoffSession.application_id == application.id,
        ManualHandoffSession.status.in_(ACTIVE_HANDOFF_STATUSES),
    ).first():
        raise JT5ResolutionError("Close the retained handoff before resolving non-submission")
    reviews = db.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
        ManualReviewTask.status.in_([ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value]),
    ).all()
    if any((review.details or {}).get("attempt_reference") != attempt.reference for review in reviews):
        raise JT5ResolutionError("An unrelated review remains open; recovery cannot clear that blocker")
    require_idle_onehost_worker()


def _resolve_state(db, application, attempt, outcome, payload):
    current = normalize_state(application.automation_state)
    if current not in {"submission_uncertain", "ready_to_apply"}:
        raise JT5ResolutionError("Application state changed; reload before resolving the outcome")
    if current == "ready_to_apply":
        transition_application_state(db, application, "submission_uncertain", "jt5_resolution_started", payload)
    if outcome == "confirmed":
        transition_application_state(db, application, "confirmed", "jt5_owner_confirmation_recorded", payload)
        if application.status in {ApplicationStatus.pending, ApplicationStatus.applying}:
            application.status = ApplicationStatus.applied
        application.applied_at = application.applied_at or datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        transition_application_state(db, application, "failed", "jt5_owner_non_submission_recorded", payload)
        application.status = ApplicationStatus.pending
    related = db.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
        ManualReviewTask.status.in_([ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value]),
    ).all()
    for review in related:
        if (review.details or {}).get("attempt_reference") == attempt.reference:
            review.status = ManualReviewStatus.resolved.value
            review.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
            review.resolution_notes = "Outcome recorded in the JT5 owner resolution audit."
    if outcome == "not_submitted":
        transition_application_state(db, application, "ready_to_apply", "jt5_explicit_retry_available", payload)


def resolve_jt5_outcome(db, *, application_id, user_id, data):
    """Resolve one exact attempt atomically. The caller owns commit/rollback."""
    application = db.query(Application).filter(
        Application.id == application_id, Application.user_id == user_id,
    ).with_for_update(nowait=True).populate_existing().first()
    if application is None:
        raise LookupError("Application not found")
    attempt = db.query(SubmissionAttempt).filter(
        SubmissionAttempt.application_id == application_id,
        SubmissionAttempt.user_id == user_id,
        SubmissionAttempt.reference == data.attempt_reference,
    ).with_for_update(nowait=True).populate_existing().first()
    if attempt is None:
        raise LookupError("Attempt not found")
    request_hash = hashlib.sha256(json.dumps(data.model_dump(), sort_keys=True).encode()).hexdigest()
    previous = (attempt.attempt_metadata or {}).get("owner_resolution")
    if previous:
        if previous["request_hash"] != request_hash:
            raise JT5ResolutionError("This attempt already has a different immutable outcome resolution")
        return {**previous, "idempotent": True, "automatic_retry_allowed": False}
    latest = db.query(SubmissionAttempt.id).filter(
        SubmissionAttempt.application_id == application_id,
    ).order_by(SubmissionAttempt.id.desc()).first()
    if latest[0] != attempt.id or not _pending_resolution(attempt):
        raise JT5ResolutionError("Only the latest uncertain JT5 attempt can be resolved")
    if application.status == ApplicationStatus.withdrawn:
        raise JT5ResolutionError("A withdrawn application cannot be changed by outcome recovery")
    if normalize_state(application.automation_state) not in {"submission_uncertain", "ready_to_apply"}:
        raise JT5ResolutionError("Application state changed; reload before resolving the outcome")
    if db.query(SubmissionAttempt.id).filter(
        SubmissionAttempt.application_id == application_id,
        SubmissionAttempt.id != attempt.id,
        SubmissionAttempt.status.in_(["queued", "in_progress", "uncertain"]),
    ).first():
        raise JT5ResolutionError("Another unresolved attempt exists for this application")
    snapshot = None
    if data.outcome == "confirmed":
        snapshot = _verify_confirmation(db, application, attempt, data)
    else:
        _verify_non_submission(db, application, attempt, data)
    receipt = {
        **data.model_dump(), "request_hash": request_hash,
        "reviewer_user_id": user_id, "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "original_attempt_status": attempt.status,
        "original_result": (attempt.attempt_metadata or {}).get("result"),
        "evidence_snapshot_hash": snapshot["evidence_snapshot_hash"] if snapshot else None,
        "finding_source": "authenticated_owner_review",
        "automatic_retry_allowed": False,
    }
    payload = {"attempt_reference": attempt.reference, "reviewer_user_id": user_id,
               "outcome": data.outcome, "request_hash": request_hash}
    _resolve_state(db, application, attempt, data.outcome, payload)
    complete_jt5_attempt(db, attempt, outcome="confirmed" if data.outcome == "confirmed" else "failed_pre_submit",
                         details={"reason": "owner_reviewed_outcome", "resolution_request_hash": request_hash})
    attempt.attempt_metadata = {**(attempt.attempt_metadata or {}), "dispatch_status": "reconciled", "owner_resolution": receipt}
    db.flush()
    return {**receipt, "idempotent": False}
