"""Ordinary Lever path reliability.

This module closes the bookkeeping around the supported Lever flow:

prepare -> fill -> Answer Vault interruption -> resume the same application
-> another question if needed -> resume -> owner final action -> explicit
confirmation -> evidence -> applied/confirmed -> close handoff -> block duplicate.

It does not submit, does not solve CAPTCHA, and does not revive the old
Chromium campaign. A URL change alone is never confirmation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
    SubmissionEvidence,
    SubmissionEvidenceType,
)
from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job
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
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.utcnow()


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _target(url: str) -> Dict[str, Optional[str]]:
    site, posting_id, region = parse_lever_job_url(url)
    return {"site": site, "posting_id": posting_id, "region": region, "url": str(url or "").strip()}


def _same_target(left: str, right: str) -> bool:
    a = _target(left)
    b = _target(right)
    return bool(a["site"] and a["posting_id"] and a == {**b, "url": b["url"]} or (
        a["site"] == b["site"] and a["posting_id"] == b["posting_id"] and a["region"] == b["region"]
    ))


def _ledger(application: Application) -> Dict[str, Any]:
    metadata = dict(application.application_target_metadata or {})
    ledger = dict(metadata.get(CONTINUITY_KEY) or {})
    metadata[CONTINUITY_KEY] = ledger
    application.application_target_metadata = metadata
    return ledger


def _event(db: Session, application: Application, event_type: str, to_state: str, payload: Mapping[str, Any]) -> None:
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type=event_type,
            from_state=application.automation_state,
            to_state=to_state,
            payload=dict(payload),
        )
    )


def explicit_confirmation(final_url: str, confirmation_text: str) -> bool:
    text = _normalize(confirmation_text)
    if not any(phrase in text for phrase in EXPLICIT_CONFIRMATION_PHRASES):
        return False
    path = urlparse(final_url or "").path.lower()
    return "/thanks" in path or any(phrase in text for phrase in EXPLICIT_CONFIRMATION_PHRASES)


def duplicate_blocker(db: Session, application: Application, job: Job) -> Optional[str]:
    site, posting_id, _region = parse_lever_job_url(str(job.url or ""))
    if not site or not posting_id:
        return "lever_target_unverified"
    siblings = (
        db.query(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .filter(Application.user_id == application.user_id, Application.id != application.id)
        .all()
    )
    for other, other_job in siblings:
        other_site, other_posting, _other_region = parse_lever_job_url(str(other_job.url or ""))
        confirmed = other.status == ApplicationStatus.applied or other.automation_state in {
            ApplicationAutomationState.confirmed.value,
            ApplicationAutomationState.submitted.value,
        }
        if other_site == site and other_posting == posting_id and confirmed:
            return "duplicate_lever_submission_blocked"
    if application.status == ApplicationStatus.applied or application.automation_state == ApplicationAutomationState.confirmed.value:
        return "application_already_confirmed"
    return None


def record_answer_vault_interruption(
    db: Session,
    application: Application,
    job: Job,
    *,
    question: str,
    current_url: str,
) -> Dict[str, Any]:
    """Keep an unknown-question pause on the same Lever application."""

    if not _same_target(str(job.url or ""), current_url):
        raise LeverOrdinaryPathError("target_continuity_broken", "Answer Vault interruption left the retained Lever target")
    blocker = duplicate_blocker(db, application, job)
    if blocker:
        raise LeverOrdinaryPathError(blocker, "Confirmed Lever target cannot be interrupted or refilled")
    ledger = _ledger(application)
    interruptions = list(ledger.get("interruptions") or [])
    interruptions.append({
        "question": str(question or "").strip(),
        "url": current_url,
        "application_id": application.id,
        "posting_id": _target(current_url)["posting_id"],
        "at": _now().isoformat(),
    })
    ledger["interruptions"] = interruptions
    ledger["application_id"] = application.id
    ledger["posting_id"] = _target(str(job.url or ""))["posting_id"]
    application.automation_state = ApplicationAutomationState.needs_review.value
    _event(db, application, "lever_answer_vault_interruption", application.automation_state, {
        "application_id": application.id,
        "question": str(question or "").strip(),
        "same_target": True,
    })
    db.flush()
    return {"application_id": application.id, "interruption_count": len(interruptions), "same_target": True}


def resume_same_application(
    db: Session,
    application: Application,
    job: Job,
    *,
    current_url: str,
) -> Dict[str, Any]:
    if not _same_target(str(job.url or ""), current_url):
        raise LeverOrdinaryPathError("target_continuity_broken", "Resume target does not match the retained Lever application")
    blocker = duplicate_blocker(db, application, job)
    if blocker:
        raise LeverOrdinaryPathError(blocker, "Confirmed Lever target cannot be resumed into another submission")
    ledger = _ledger(application)
    if ledger.get("application_id") not in {None, application.id}:
        raise LeverOrdinaryPathError("application_continuity_broken", "Resume pointed at a different application")
    ledger["application_id"] = application.id
    ledger["resume_count"] = int(ledger.get("resume_count") or 0) + 1
    ledger["posting_id"] = _target(current_url)["posting_id"]
    application.automation_state = ApplicationAutomationState.applying.value
    _event(db, application, "lever_same_application_resumed", application.automation_state, {
        "application_id": application.id,
        "resume_count": ledger["resume_count"],
        "posting_id": ledger["posting_id"],
    })
    db.flush()
    return {"application_id": application.id, "resume_count": ledger["resume_count"], "opened_new_application": False}


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
    """Persist explicit confirmation evidence before any state promotion."""

    if not target_verified or not _same_target(str(job.url or ""), final_url):
        application.automation_state = ApplicationAutomationState.submission_uncertain.value
        _event(db, application, "lever_confirmation_rejected", application.automation_state, {
            "reason": "stale_or_unverified_target",
        })
        db.flush()
        raise LeverOrdinaryPathError("stale_or_unverified_target", "Lever confirmation target is not the retained posting")
    if not explicit_confirmation(final_url, confirmation_text):
        application.automation_state = ApplicationAutomationState.submission_uncertain.value
        _event(db, application, "lever_confirmation_rejected", application.automation_state, {
            "reason": "confirmation_not_explicit",
        })
        db.flush()
        raise LeverOrdinaryPathError("confirmation_not_explicit", "Lever confirmation is missing an explicit success phrase")
    blocker = duplicate_blocker(db, application, job)
    if blocker == "duplicate_lever_submission_blocked":
        raise LeverOrdinaryPathError(blocker, "This Lever posting is already confirmed")

    evidence = SubmissionEvidence(
        application_id=application.id,
        evidence_type=SubmissionEvidenceType.confirmation_page.value,
        is_sufficient=True,
        final_url=final_url,
        confirmation_text=confirmation_text,
        evidence_metadata={
            "platform": "lever",
            "target_verified": True,
            "approval_reference": approval_reference,
            "posting_id": _target(final_url)["posting_id"],
            "site": _target(final_url)["site"],
        },
    )
    db.add(evidence)
    db.flush()
    _event(db, application, "lever_confirmation_evidence_persisted", application.automation_state, {
        "evidence_id": evidence.id,
        "before_promotion": True,
    })
    application.status = ApplicationStatus.applied
    application.automation_state = ApplicationAutomationState.confirmed.value
    application.applied_at = _now()
    _close_reviews_and_handoffs(db, application)
    _event(db, application, "lever_ordinary_path_confirmed", application.automation_state, {
        "evidence_id": evidence.id,
        "approval_reference": approval_reference,
    })
    db.flush()
    return {
        "application_id": application.id,
        "status": application.status.value,
        "automation_state": application.automation_state,
        "evidence_id": evidence.id,
        "confirmed": True,
    }


def _close_reviews_and_handoffs(db: Session, application: Application) -> None:
    reviews = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == application.id,
            ManualReviewTask.status.in_([ManualReviewStatus.open.value, ManualReviewStatus.in_progress.value]),
        )
        .all()
    )
    for review in reviews:
        review.status = ManualReviewStatus.resolved.value
        review.resolved_at = _now()
        review.resolution_notes = "Closed after explicit Lever confirmation evidence."
    handoffs = (
        db.query(ManualHandoffSession)
        .filter(
            ManualHandoffSession.application_id == application.id,
            ManualHandoffSession.status.in_([
                HandoffSessionStatus.awaiting_user.value,
                HandoffSessionStatus.claimed.value,
                HandoffSessionStatus.ready_to_resume.value,
                HandoffSessionStatus.resuming.value,
            ]),
        )
        .all()
    )
    for session in handoffs:
        session.status = HandoffSessionStatus.completed.value
        session.completed_at = _now()


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
    """Recover a stuck pending/applying application without inventing confirmation."""

    current = now or _now()
    evidence = (
        db.query(SubmissionEvidence)
        .filter(SubmissionEvidence.application_id == application.id, SubmissionEvidence.is_sufficient.is_(True))
        .first()
    )
    if evidence and evidence.final_url and evidence.confirmation_text:
        return reconcile_lever_confirmation(
            db,
            application,
            job,
            final_url=evidence.final_url,
            confirmation_text=evidence.confirmation_text,
            target_verified=True,
        )
    if final_url and confirmation_text and target_verified:
        return reconcile_lever_confirmation(
            db,
            application,
            job,
            final_url=final_url,
            confirmation_text=confirmation_text,
            target_verified=True,
        )
    updated = application.updated_at or application.created_at or current
    if getattr(updated, "tzinfo", None) is not None:
        updated = updated.replace(tzinfo=None)
    stranded = application.automation_state in {
        ApplicationAutomationState.preparing.value,
        ApplicationAutomationState.applying.value,
        ApplicationAutomationState.needs_review.value,
    } or application.status == ApplicationStatus.applying
    if stranded and current - updated >= stale_after:
        application.automation_state = ApplicationAutomationState.submission_uncertain.value
        _event(db, application, "lever_stranded_application_recovered", application.automation_state, {
            "reason": "no_explicit_confirmation",
        })
        db.flush()
        return {"application_id": application.id, "automation_state": application.automation_state, "confirmed": False}
    return {"application_id": application.id, "automation_state": application.automation_state, "confirmed": False}
