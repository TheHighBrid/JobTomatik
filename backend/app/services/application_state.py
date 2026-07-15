from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
    SubmissionEvidenceType,
)


_ALLOWED_TRANSITIONS = {
    ApplicationAutomationState.preparing.value: {
        ApplicationAutomationState.ready_to_apply.value,
        ApplicationAutomationState.applying.value,
        ApplicationAutomationState.needs_review.value,
        ApplicationAutomationState.failed.value,
        ApplicationAutomationState.withdrawn.value,
    },
    ApplicationAutomationState.ready_to_apply.value: {
        ApplicationAutomationState.applying.value,
        ApplicationAutomationState.needs_review.value,
        ApplicationAutomationState.failed.value,
        ApplicationAutomationState.withdrawn.value,
    },
    ApplicationAutomationState.applying.value: {
        ApplicationAutomationState.ready_to_apply.value,
        ApplicationAutomationState.needs_review.value,
        ApplicationAutomationState.submission_uncertain.value,
        ApplicationAutomationState.submitted.value,
        ApplicationAutomationState.failed.value,
    },
    ApplicationAutomationState.needs_review.value: {
        ApplicationAutomationState.ready_to_apply.value,
        ApplicationAutomationState.applying.value,
        ApplicationAutomationState.failed.value,
        ApplicationAutomationState.withdrawn.value,
    },
    ApplicationAutomationState.submission_uncertain.value: {
        ApplicationAutomationState.submitted.value,
        ApplicationAutomationState.needs_review.value,
        ApplicationAutomationState.failed.value,
    },
    ApplicationAutomationState.submitted.value: {
        ApplicationAutomationState.confirmed.value,
        ApplicationAutomationState.needs_review.value,
    },
    ApplicationAutomationState.confirmed.value: set(),
    ApplicationAutomationState.failed.value: {
        ApplicationAutomationState.preparing.value,
        ApplicationAutomationState.ready_to_apply.value,
        ApplicationAutomationState.withdrawn.value,
    },
    ApplicationAutomationState.withdrawn.value: set(),
}


class InvalidApplicationTransition(ValueError):
    pass


def normalize_state(value: Any) -> str:
    if isinstance(value, ApplicationAutomationState):
        return value.value
    return str(value or ApplicationAutomationState.preparing.value)


def transition_application_state(
    db: Session,
    application: Application,
    new_state: ApplicationAutomationState | str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    allow_same: bool = True,
) -> ApplicationEvent:
    current = normalize_state(application.automation_state)
    target = normalize_state(new_state)

    if current == target and allow_same:
        event = ApplicationEvent(
            application_id=application.id,
            event_type=event_type,
            from_state=current,
            to_state=target,
            payload=payload or {},
        )
        db.add(event)
        return event

    allowed = _ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidApplicationTransition(f"Invalid application transition: {current} -> {target}")

    application.automation_state = target
    event = ApplicationEvent(
        application_id=application.id,
        event_type=event_type,
        from_state=current,
        to_state=target,
        payload=payload or {},
    )
    db.add(event)
    return event


def create_manual_review_task(
    db: Session,
    application: Application,
    reason_code: ManualReviewReason | str,
    summary: str,
    *,
    details: Optional[Dict[str, Any]] = None,
    blocking_url: Optional[str] = None,
    screenshot_path: Optional[str] = None,
    resume_token: Optional[str] = None,
    target_state: ApplicationAutomationState | str = ApplicationAutomationState.needs_review,
) -> ManualReviewTask:
    reason = reason_code.value if isinstance(reason_code, ManualReviewReason) else str(reason_code)
    existing = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == application.id,
            ManualReviewTask.reason_code == reason,
            ManualReviewTask.status.in_([
                ManualReviewStatus.open.value,
                ManualReviewStatus.in_progress.value,
            ]),
        )
        .order_by(ManualReviewTask.created_at.desc())
        .first()
    )
    if existing:
        existing.summary = summary
        existing.details = details or existing.details or {}
        existing.blocking_url = blocking_url or existing.blocking_url
        existing.screenshot_path = screenshot_path or existing.screenshot_path
        existing.resume_token = resume_token or existing.resume_token
        current = normalize_state(application.automation_state)
        target = normalize_state(target_state)
        if current != target:
            transition_application_state(
                db,
                application,
                target,
                "manual_review_reopened",
                {"reason_code": reason, "review_id": existing.id},
            )
        return existing

    review = ManualReviewTask(
        application_id=application.id,
        reason_code=reason,
        summary=summary,
        details=details or {},
        blocking_url=blocking_url,
        screenshot_path=screenshot_path,
        resume_token=resume_token,
    )
    db.add(review)
    transition_application_state(
        db,
        application,
        target_state,
        "manual_review_created",
        {"reason_code": reason, "summary": summary},
    )
    return review


def resolve_manual_review_task(
    db: Session,
    application: Application,
    review: ManualReviewTask,
    resolution_notes: Optional[str] = None,
) -> ManualReviewTask:
    review.status = ManualReviewStatus.resolved.value
    review.resolved_at = datetime.utcnow()
    review.resolution_notes = resolution_notes
    current = normalize_state(application.automation_state)
    if current == ApplicationAutomationState.needs_review.value:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.ready_to_apply,
            "manual_review_resolved",
            {"review_id": review.id, "reason_code": review.reason_code},
        )
    else:
        db.add(ApplicationEvent(
            application_id=application.id,
            event_type="manual_review_resolved",
            from_state=current,
            to_state=current,
            payload={"review_id": review.id, "reason_code": review.reason_code},
        ))
    return review


def record_submission_evidence(
    db: Session,
    application: Application,
    evidence_type: SubmissionEvidenceType | str,
    *,
    is_sufficient: bool,
    final_url: Optional[str] = None,
    confirmation_text: Optional[str] = None,
    selector: Optional[str] = None,
    external_application_id: Optional[str] = None,
    screenshot_path: Optional[str] = None,
    html_snapshot_path: Optional[str] = None,
    payload_hash: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SubmissionEvidence:
    evidence = SubmissionEvidence(
        application_id=application.id,
        evidence_type=(evidence_type.value if isinstance(evidence_type, SubmissionEvidenceType) else str(evidence_type)),
        is_sufficient=is_sufficient,
        final_url=final_url,
        confirmation_text=confirmation_text,
        selector=selector,
        external_application_id=external_application_id,
        screenshot_path=screenshot_path,
        html_snapshot_path=html_snapshot_path,
        payload_hash=payload_hash,
        evidence_metadata=metadata or {},
    )
    db.add(evidence)
    return evidence


def has_sufficient_submission_evidence(db: Session, application_id: int) -> bool:
    return (
        db.query(SubmissionEvidence.id)
        .filter(
            SubmissionEvidence.application_id == application_id,
            SubmissionEvidence.is_sufficient.is_(True),
        )
        .first()
        is not None
    )
