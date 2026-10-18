"""
Audited owner resolution of uncertain JT5 attempts without automatic replay.

Confirmation requires readable, retained, attempt-bound evidence and closed
handoffs. Non-submission requests remain blocked until a durable employer-evidence
intake and verification contract exists. Notes never release a retry block.
No browser, employer request, approval, queue publication, or release flag change
is performed here.
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


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _readable_signal(evidence):
    signals = (evidence.confirmation_text, evidence.external_application_id)
    return any(str(value or "").strip() for value in signals)


def _confirmation_snapshot(evidence, attempt):
    if not evidence.is_sufficient or evidence.evidence_type not in STRONG_EVIDENCE_TYPES:
        raise JT5ResolutionError("Retained sufficient confirmation evidence is required")
    if not evidence.captured_at or _utc(evidence.captured_at) < _utc(attempt.queued_at):
        raise JT5ResolutionError("The evidence predates this attempt")
    metadata = evidence.evidence_metadata or {}
    bindings = ("attempt_reference", "jt5_worker_attempt_reference")
    if any(metadata.get(key) != attempt.reference for key in bindings):
        raise JT5ResolutionError("The evidence lacks matching trusted worker and attempt bindings")
    if not _readable_signal(evidence):
        raise JT5ResolutionError("Readable confirmation text or an employer receipt ID is required")
    return build_evidence_snapshot(evidence)


def _evidence_rejected(db, evidence_id, snapshot_hash):
    return db.query(SubmissionEvidenceReview.id).filter(
        SubmissionEvidenceReview.evidence_id == evidence_id,
        SubmissionEvidenceReview.evidence_snapshot_hash == snapshot_hash,
        SubmissionEvidenceReview.decision == "rejected",
    ).first() is not None


def _pending_resolution(attempt):
    metadata = attempt.attempt_metadata or {}
    return metadata.get("execution_contract") == "jt5" and (
        attempt.status == "uncertain"
        or (attempt.status == "queued" and metadata.get("dispatch_status") == "reconciliation_required")
    )


def _confirmation_choices(db, application, attempt):
    options = []
    evidence_rows = db.query(SubmissionEvidence).filter(
        SubmissionEvidence.application_id == application.id,
    ).order_by(SubmissionEvidence.id.desc()).all()
    for evidence in evidence_rows:
        try:
            snapshot = _confirmation_snapshot(evidence, attempt)
        except JT5ResolutionError:
            continue
        snapshot_hash = snapshot["evidence_snapshot_hash"]
        if _evidence_rejected(db, evidence.id, snapshot_hash):
            continue
        options.append({
            "id": evidence.id, "evidence_type": evidence.evidence_type,
            "snapshot_hash": snapshot_hash, "confirmation_text": evidence.confirmation_text,
            "final_url": evidence.final_url, "external_application_id": evidence.external_application_id,
        })
    return options


def _context_blockers(db, application, attempt):
    try:
        _require_resolvable_attempt(db, application, attempt)
        _require_closed_handoffs(db, application, lock=False)
    except JT5ResolutionError as exc:
        return [str(exc)]
    return []


def resolution_context(db, application):
    """Read-only recovery context; does not inspect or contact the browser/worker."""
    attempt = db.query(SubmissionAttempt).filter(
        SubmissionAttempt.application_id == application.id,
    ).order_by(SubmissionAttempt.id.desc()).first()
    required = bool(attempt and _pending_resolution(attempt))
    blockers = _context_blockers(db, application, attempt) if required else []
    options = _confirmation_choices(db, application, attempt) if required and not blockers else []
    return {
        "attempt_reference": attempt.reference if attempt else None,
        "resolution_required": required,
        "resolution_available": bool(options),
        "blockers": blockers,
        "confirmation_evidence": options,
        "resolution": (attempt.attempt_metadata or {}).get("owner_resolution") if attempt else None,
        "automatic_retry_allowed": False,
        "non_submission_resolution_available": False,
    }


def _verify_confirmation(db, application, attempt, data):
    if data.evidence_source != "retained_confirmation" or not data.evidence_id:
        raise JT5ResolutionError("Select retained confirmation evidence for this application")
    if data.evidence_reference != f"submission-evidence:{data.evidence_id}":
        raise JT5ResolutionError("The evidence reference must identify the selected retained record")
    evidence = db.query(SubmissionEvidence).filter(
        SubmissionEvidence.id == data.evidence_id,
        SubmissionEvidence.application_id == application.id,
    ).with_for_update().populate_existing().first()
    if evidence is None:
        raise JT5ResolutionError("Confirmation evidence was not found for this application")
    snapshot = _confirmation_snapshot(evidence, attempt)
    if data.evidence_snapshot_hash != snapshot["evidence_snapshot_hash"]:
        raise JT5ResolutionError("The evidence changed; reload it before recording a decision")
    if _evidence_rejected(db, evidence.id, snapshot["evidence_snapshot_hash"]):
        raise JT5ResolutionError("This confirmation evidence was rejected during review")
    return snapshot



def _consume_confirmation_review(db, application, attempt, user_id, evidence_id, snapshot_hash, request_hash):
    """
    Atomically consume the verified snapshot so later rejection conflicts.

    The unique (evidence_id, evidence_snapshot_hash) constraint serializes
    simultaneous owner recovery and independent evidence-review decisions.
    This runs after locking attempt, application and the exact evidence row.
    """
    existing = db.query(SubmissionEvidenceReview).filter(
        SubmissionEvidenceReview.evidence_id == evidence_id,
        SubmissionEvidenceReview.evidence_snapshot_hash == snapshot_hash,
    ).with_for_update().first()
    if existing is not None:
        if existing.decision != "accepted":
            raise JT5ResolutionError("This confirmation evidence was rejected during review")
        return existing

    review = SubmissionEvidenceReview(
        application_id=application.id,
        evidence_id=evidence_id,
        reviewer_user_id=user_id,
        decision="accepted",
        evidence_snapshot_hash=snapshot_hash,
        review_notes="Verified owner confirmation consumed by JT5 outcome recovery.",
        review_metadata={
            "review_source": "jt5_owner_resolution",
            "attempt_reference": attempt.reference,
            "resolution_request_hash": request_hash,
        },
    )
    db.add(review)
    # Reserve the snapshot in the same transaction before confirming outcome.
    db.flush()
    return review

def _require_closed_handoffs(db, application, *, lock=True):
    query = db.query(ManualHandoffSession).filter(
        ManualHandoffSession.application_id == application.id,
        ManualHandoffSession.status.in_(ACTIVE_HANDOFF_STATUSES),
    )
    if lock:
        query = query.with_for_update(nowait=True).populate_existing()
    if query.first() is not None:
        raise JT5ResolutionError("Close the retained handoff before recording confirmation")


def _resolve_state(db, application, attempt, payload):
    current = normalize_state(application.automation_state)
    if current == "ready_to_apply":
        transition_application_state(db, application, "submission_uncertain", "jt5_resolution_started", payload)
    transition_application_state(db, application, "confirmed", "jt5_owner_confirmation_recorded", payload)
    if application.status in {ApplicationStatus.pending, ApplicationStatus.applying}:
        application.status = ApplicationStatus.applied
    application.applied_at = application.applied_at or datetime.now(timezone.utc).replace(tzinfo=None)
    related = db.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
        ManualReviewTask.status.in_([ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value]),
    ).all()
    for review in related:
        if (review.details or {}).get("attempt_reference") == attempt.reference:
            review.status = ManualReviewStatus.resolved.value
            review.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
            review.resolution_notes = "Outcome recorded in the JT5 owner resolution audit."


def _owned_locked_records(db, application_id, user_id, reference):
    owned = db.query(Application.id).filter(
        Application.id == application_id, Application.user_id == user_id,
    ).first()
    if owned is None:
        raise LookupError("Application not found")
    attempt = db.query(SubmissionAttempt).filter(
        SubmissionAttempt.application_id == application_id,
        SubmissionAttempt.user_id == user_id,
        SubmissionAttempt.reference == reference,
    ).with_for_update(nowait=True).populate_existing().first()
    if attempt is None:
        raise LookupError("Attempt not found")
    application = db.query(Application).filter(
        Application.id == application_id, Application.user_id == user_id,
    ).with_for_update(nowait=True).populate_existing().first()
    if application is None:
        raise LookupError("Application not found")
    return application, attempt


def _existing_resolution(attempt, request_hash):
    previous = (attempt.attempt_metadata or {}).get("owner_resolution")
    if previous:
        if previous["request_hash"] != request_hash:
            raise JT5ResolutionError("This attempt already has a different immutable outcome resolution")
        return {**previous, "idempotent": True, "automatic_retry_allowed": False}
    return None


def _require_resolvable_attempt(db, application, attempt):
    latest = db.query(SubmissionAttempt.id).filter(
        SubmissionAttempt.application_id == application.id,
    ).order_by(SubmissionAttempt.id.desc()).first()
    if latest[0] != attempt.id or not _pending_resolution(attempt):
        raise JT5ResolutionError("Only the latest uncertain JT5 attempt can be resolved")
    if application.status == ApplicationStatus.withdrawn:
        raise JT5ResolutionError("A withdrawn application cannot be changed by outcome recovery")
    if normalize_state(application.automation_state) not in {"submission_uncertain", "ready_to_apply"}:
        raise JT5ResolutionError("Application state changed; reload before resolving the outcome")
    if db.query(SubmissionAttempt.id).filter(
        SubmissionAttempt.application_id == application.id,
        SubmissionAttempt.id != attempt.id,
        SubmissionAttempt.status.in_(["queued", "in_progress", "uncertain"]),
    ).first():
        raise JT5ResolutionError("Another unresolved attempt exists for this application")


def _resolution_receipt(attempt, data, request_hash, user_id, snapshot):
    # Keep raw worker errors in the protected original attempt record, not in
    # the owner-visible recovery receipt or subsequent reconciliation GET.
    result = (attempt.attempt_metadata or {}).get("result")
    result_hash = (
        hashlib.sha256(json.dumps(result, sort_keys=True, default=str,
                                  separators=(",", ":")).encode()).hexdigest()
        if result is not None else None
    )
    return {
        **data.model_dump(), "request_hash": request_hash,
        "reviewer_user_id": user_id, "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "original_attempt_status": attempt.status,
        "original_result_sha256": result_hash,
        "evidence_snapshot_hash": snapshot["evidence_snapshot_hash"] if snapshot else None,
        "finding_source": "authenticated_owner_review",
        "automatic_retry_allowed": False,
    }


def resolve_jt5_outcome(db, *, application_id, user_id, data):
    """Resolve one exact attempt atomically. The caller owns commit/rollback."""
    application, attempt = _owned_locked_records(db, application_id, user_id, data.attempt_reference)
    request_hash = hashlib.sha256(json.dumps(data.model_dump(), sort_keys=True).encode()).hexdigest()
    previous = _existing_resolution(attempt, request_hash)
    if previous:
        return previous
    _require_resolvable_attempt(db, application, attempt)
    if data.outcome != "confirmed":
        raise JT5ResolutionError("Durable employer non-submission evidence is not supported here; retry remains blocked")
    _require_closed_handoffs(db, application)
    snapshot = _verify_confirmation(db, application, attempt, data)
    _consume_confirmation_review(
        db, application, attempt, user_id, data.evidence_id,
        snapshot["evidence_snapshot_hash"], request_hash,
    )
    receipt = _resolution_receipt(attempt, data, request_hash, user_id, snapshot)
    # The normal completion helper replaces metadata["result"] with the new
    # outcome. Preserve the original worker result privately, never in the
    # owner-facing resolution receipt.
    original_worker_result = (attempt.attempt_metadata or {}).get("result")
    payload = {"attempt_reference": attempt.reference, "reviewer_user_id": user_id,
               "outcome": data.outcome, "request_hash": request_hash}
    _resolve_state(db, application, attempt, payload)
    complete_jt5_attempt(db, attempt, outcome="confirmed",
                         details={"reason": "owner_reviewed_outcome", "resolution_request_hash": request_hash})
    attempt.attempt_metadata = {
        **(attempt.attempt_metadata or {}),
        "dispatch_status": "reconciled",
        "jt5_original_result": original_worker_result,
        "owner_resolution": receipt,
    }
    db.flush()
    return {**receipt, "idempotent": False}
