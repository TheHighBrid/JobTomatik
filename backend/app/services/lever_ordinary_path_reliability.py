"""Fail-closed reliability bookkeeping for the supported ordinary Lever path."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Mapping, Optional

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
    SubmissionEvidenceType,
)
from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job
from app.services.application_state import (
    InvalidApplicationTransition,
    transition_application_state,
)
from app.services.ats_lever import parse_lever_job_url


EXPLICIT_CONFIRMATION_PHRASES = (
    "thank you for applying",
    "thank you for your application",
    "thanks for applying",
    "thanks for your application",
    "application submitted",
    "application received",
    "your application has been submitted",
    "your application was submitted",
    "application successfully submitted",
    "successfully submitted your application",
    "we have received your application",
    "we've received your application",
)
CONTINUITY_KEY = "lever_ordinary_path"
STALE_AFTER = timedelta(hours=6)


class LeverOrdinaryPathError(ValueError):
    """Raised when ordinary-path continuity or confirmation cannot be proven."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.utcnow()


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _target(url: str) -> Dict[str, Optional[str]]:
    site, posting_id, region = parse_lever_job_url(url)
    return {
        "site": site,
        "posting_id": posting_id,
        "region": region,
    }


def _same_target(left: str, right: str) -> bool:
    left_target = _target(left)
    right_target = _target(right)
    return bool(
        left_target["site"]
        and left_target["posting_id"]
        and left_target == right_target
    )


def _ledger(application: Application) -> Dict[str, Any]:
    metadata = dict(application.application_target_metadata or {})
    ledger = dict(metadata.get(CONTINUITY_KEY) or {})
    metadata[CONTINUITY_KEY] = ledger
    application.application_target_metadata = metadata
    return ledger


def _move(
    db: Session,
    application: Application,
    state: str,
    event_type: str,
    payload: Mapping[str, Any],
) -> None:
    try:
        transition_application_state(
            db,
            application,
            state,
            event_type,
            dict(payload),
        )
    except InvalidApplicationTransition as exc:
        raise LeverOrdinaryPathError(
            "invalid_state_transition",
            str(exc),
        ) from exc


def explicit_confirmation(final_url: str, confirmation_text: str) -> bool:
    """Return true only for a non-empty target carrying an explicit success phrase."""
    if not str(final_url or "").strip():
        return False
    text = _normalize(confirmation_text)
    return any(
        phrase in text
        for phrase in EXPLICIT_CONFIRMATION_PHRASES
    )


def _application_is_confirmed(application: Application) -> bool:
    return (
        application.status == ApplicationStatus.applied
        or application.automation_state
        in {
            ApplicationAutomationState.confirmed.value,
            ApplicationAutomationState.submitted.value,
        }
    )


def _confirmed_sibling_matches(
    db: Session,
    application: Application,
    *,
    site: str,
    posting_id: str,
) -> bool:
    siblings = (
        db.query(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .filter(
            Application.user_id == application.user_id,
            Application.id != application.id,
        )
        .all()
    )
    for other, other_job in siblings:
        other_site, other_posting, _ = parse_lever_job_url(
            str(other_job.url or "")
        )
        if (
            other_site == site
            and other_posting == posting_id
            and _application_is_confirmed(other)
        ):
            return True
    return False


def duplicate_blocker(
    db: Session,
    application: Application,
    job: Job,
) -> Optional[str]:
    """Return a duplicate/replay blocker for the retained Lever posting."""
    site, posting_id, _ = parse_lever_job_url(str(job.url or ""))
    if not site or not posting_id:
        return "lever_target_unverified"
    if _confirmed_sibling_matches(
        db,
        application,
        site=site,
        posting_id=posting_id,
    ):
        return "duplicate_lever_submission_blocked"
    if _application_is_confirmed(application):
        return "application_already_confirmed"
    return None


def _require_same_target(job: Job, current_url: str, message: str) -> None:
    if not _same_target(str(job.url or ""), current_url):
        raise LeverOrdinaryPathError(
            "target_continuity_broken",
            message,
        )


def record_answer_vault_interruption(
    db: Session,
    application: Application,
    job: Job,
    *,
    question: str,
    current_url: str,
) -> Dict[str, Any]:
    """Persist an Answer Vault interruption without changing the application."""
    _require_same_target(
        job,
        current_url,
        "Answer Vault interruption left the retained Lever target",
    )
    blocker = duplicate_blocker(db, application, job)
    if blocker:
        raise LeverOrdinaryPathError(
            blocker,
            "Confirmed Lever target cannot be interrupted or refilled",
        )

    ledger = _ledger(application)
    interruptions = list(ledger.get("interruptions") or [])
    interruptions.append(
        {
            "question": str(question or "").strip(),
            "url": current_url,
            "application_id": application.id,
            "posting_id": _target(current_url)["posting_id"],
            "at": _now().isoformat(),
        }
    )
    ledger["interruptions"] = interruptions
    ledger["application_id"] = application.id
    ledger["posting_id"] = _target(str(job.url or ""))["posting_id"]
    _move(
        db,
        application,
        ApplicationAutomationState.needs_review.value,
        "lever_answer_vault_interruption",
        {
            "application_id": application.id,
            "question": str(question or "").strip(),
            "same_target": True,
        },
    )
    db.flush()
    return {
        "application_id": application.id,
        "interruption_count": len(interruptions),
        "same_target": True,
    }


def resume_same_application(
    db: Session,
    application: Application,
    job: Job,
    *,
    current_url: str,
) -> Dict[str, Any]:
    """Resume only the retained Lever application and posting."""
    _require_same_target(
        job,
        current_url,
        "Resume target does not match the retained Lever application",
    )
    blocker = duplicate_blocker(db, application, job)
    if blocker:
        raise LeverOrdinaryPathError(
            blocker,
            "Confirmed Lever target cannot be resumed into another submission",
        )

    ledger = _ledger(application)
    if ledger.get("application_id") not in {None, application.id}:
        raise LeverOrdinaryPathError(
            "application_continuity_broken",
            "Resume pointed at a different application",
        )
    ledger["application_id"] = application.id
    ledger["resume_count"] = int(ledger.get("resume_count") or 0) + 1
    ledger["posting_id"] = _target(current_url)["posting_id"]
    _move(
        db,
        application,
        ApplicationAutomationState.applying.value,
        "lever_same_application_resumed",
        {
            "application_id": application.id,
            "resume_count": ledger["resume_count"],
            "posting_id": ledger["posting_id"],
        },
    )
    db.flush()
    return {
        "application_id": application.id,
        "resume_count": ledger["resume_count"],
        "opened_new_application": False,
    }


def _reject(
    db: Session,
    application: Application,
    reason: str,
) -> None:
    if application.automation_state == ApplicationAutomationState.applying.value:
        target_state = ApplicationAutomationState.submission_uncertain.value
    elif (
        application.automation_state
        != ApplicationAutomationState.submission_uncertain.value
    ):
        target_state = ApplicationAutomationState.needs_review.value
    else:
        return
    _move(
        db,
        application,
        target_state,
        "lever_confirmation_rejected",
        {"reason": reason},
    )


def _confirmation_evidence(
    application: Application,
    *,
    final_url: str,
    confirmation_text: str,
    approval_reference: Optional[str],
) -> SubmissionEvidence:
    target = _target(final_url)
    return SubmissionEvidence(
        application_id=application.id,
        evidence_type=SubmissionEvidenceType.confirmation_page.value,
        is_sufficient=True,
        final_url=final_url,
        confirmation_text=confirmation_text,
        evidence_metadata={
            "platform": "lever",
            "target_verified": True,
            "approval_reference": approval_reference,
            "posting_id": target["posting_id"],
            "site": target["site"],
        },
    )


def _promote_confirmation(
    db: Session,
    application: Application,
    evidence_id: int,
    approval_reference: Optional[str],
) -> None:
    _move(
        db,
        application,
        application.automation_state,
        "lever_confirmation_evidence_persisted",
        {
            "evidence_id": evidence_id,
            "before_promotion": True,
        },
    )
    if application.automation_state == ApplicationAutomationState.needs_review.value:
        _move(
            db,
            application,
            ApplicationAutomationState.applying.value,
            "lever_confirmation_resume",
            {"evidence_id": evidence_id},
        )
    if application.automation_state == ApplicationAutomationState.applying.value:
        _move(
            db,
            application,
            ApplicationAutomationState.submitted.value,
            "lever_confirmation_submitted",
            {"evidence_id": evidence_id},
        )
    _move(
        db,
        application,
        ApplicationAutomationState.confirmed.value,
        "lever_ordinary_path_confirmed",
        {
            "evidence_id": evidence_id,
            "approval_reference": approval_reference,
        },
    )


def reconcile_lever_confirmation(
    db: Session,
    application: Application,
    job: Job,
    *,
    final_url: str,
    confirmation_text: str,
    target_verified: bool,
    approval_reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Promote to confirmed only after target and success evidence are proven."""
    if not target_verified or not _same_target(str(job.url or ""), final_url):
        _reject(db, application, "stale_or_unverified_target")
        db.flush()
        raise LeverOrdinaryPathError(
            "stale_or_unverified_target",
            "Lever confirmation target is not the retained posting",
        )
    if not explicit_confirmation(final_url, confirmation_text):
        _reject(db, application, "confirmation_not_explicit")
        db.flush()
        raise LeverOrdinaryPathError(
            "confirmation_not_explicit",
            "Lever confirmation is missing an explicit success phrase",
        )
    blocker = duplicate_blocker(db, application, job)
    if blocker == "duplicate_lever_submission_blocked":
        raise LeverOrdinaryPathError(
            blocker,
            "This Lever posting is already confirmed",
        )

    evidence = _confirmation_evidence(
        application,
        final_url=final_url,
        confirmation_text=confirmation_text,
        approval_reference=approval_reference,
    )
    db.add(evidence)
    db.flush()
    _promote_confirmation(
        db,
        application,
        evidence.id,
        approval_reference,
    )
    application.status = ApplicationStatus.applied
    application.applied_at = _now()
    _close_reviews_and_handoffs(db, application)
    db.flush()
    return {
        "application_id": application.id,
        "status": application.status.value,
        "automation_state": application.automation_state,
        "evidence_id": evidence.id,
        "confirmed": True,
    }


def _close_open_reviews(
    db: Session,
    application: Application,
) -> None:
    reviews = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == application.id,
            ManualReviewTask.status.in_(
                [
                    ManualReviewStatus.open.value,
                    ManualReviewStatus.in_progress.value,
                ]
            ),
        )
        .all()
    )
    for review in reviews:
        review.status = ManualReviewStatus.resolved.value
        review.resolved_at = _now()
        review.resolution_notes = (
            "Closed after explicit Lever confirmation evidence."
        )


def _complete_active_handoffs(
    db: Session,
    application: Application,
) -> None:
    active_states = [
        HandoffSessionStatus.awaiting_user.value,
        HandoffSessionStatus.claimed.value,
        HandoffSessionStatus.ready_to_resume.value,
        HandoffSessionStatus.resuming.value,
    ]
    handoffs = (
        db.query(ManualHandoffSession)
        .filter(
            ManualHandoffSession.application_id == application.id,
            ManualHandoffSession.status.in_(active_states),
        )
        .all()
    )
    for session in handoffs:
        session.status = HandoffSessionStatus.completed.value
        session.completed_at = _now()


def _close_reviews_and_handoffs(
    db: Session,
    application: Application,
) -> None:
    _close_open_reviews(db, application)
    _complete_active_handoffs(db, application)


def _sufficient_evidence(
    db: Session,
    application: Application,
) -> Optional[SubmissionEvidence]:
    return (
        db.query(SubmissionEvidence)
        .filter(
            SubmissionEvidence.application_id == application.id,
            SubmissionEvidence.is_sufficient.is_(True),
        )
        .first()
    )


def _reconcile_existing_evidence(
    db: Session,
    application: Application,
    job: Job,
) -> Optional[Dict[str, Any]]:
    evidence = _sufficient_evidence(db, application)
    if not evidence or not evidence.final_url or not evidence.confirmation_text:
        return None
    return reconcile_lever_confirmation(
        db,
        application,
        job,
        final_url=evidence.final_url,
        confirmation_text=evidence.confirmation_text,
        target_verified=True,
    )


def _application_is_stale(
    application: Application,
    *,
    current: datetime,
    stale_after: timedelta,
) -> bool:
    updated = application.updated_at or application.created_at or current
    if getattr(updated, "tzinfo", None) is not None:
        updated = updated.replace(tzinfo=None)
    return current - updated >= stale_after


def recover_stranded_application(
    db: Session,
    application: Application,
    job: Job,
    *,
    now: Optional[datetime] = None,
    stale_after: timedelta = STALE_AFTER,
    final_url: Optional[str] = None,
    confirmation_text: Optional[str] = None,
    target_verified: bool = False,
) -> Dict[str, Any]:
    """Reconcile stale ordinary-path state without inventing confirmation."""
    reconciled = _reconcile_existing_evidence(
        db,
        application,
        job,
    )
    if reconciled is not None:
        return reconciled
    if final_url and confirmation_text and target_verified:
        return reconcile_lever_confirmation(
            db,
            application,
            job,
            final_url=final_url,
            confirmation_text=confirmation_text,
            target_verified=True,
        )

    current = now or _now()
    if not _application_is_stale(
        application,
        current=current,
        stale_after=stale_after,
    ):
        return {
            "application_id": application.id,
            "automation_state": application.automation_state,
            "confirmed": False,
        }

    if application.automation_state == ApplicationAutomationState.applying.value:
        target_state = ApplicationAutomationState.submission_uncertain.value
    elif application.automation_state in {
        ApplicationAutomationState.preparing.value,
        ApplicationAutomationState.ready_to_apply.value,
    }:
        target_state = ApplicationAutomationState.needs_review.value
    else:
        target_state = None

    if target_state is not None:
        _move(
            db,
            application,
            target_state,
            "lever_stranded_application_recovered",
            {"reason": "no_explicit_confirmation"},
        )
    db.flush()
    return {
        "application_id": application.id,
        "automation_state": application.automation_state,
        "confirmed": False,
    }
