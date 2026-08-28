"""Preparation-only intake for one current owner-selected Lever Phase B target.

This bridge exists because the original Day 15 Lever materializer is intentionally
bound to retained Phase A evidence. Current job postings discovered later may enter
the supervised workflow only after exact public Lever metadata is revalidated.

Nothing here issues an approval, enables runtime flags, queues Celery work, opens a
browser, or submits an application.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.lever_phase_b_runtime import canonical_lever_application_url
from app.services.submission_integrity import (
    DuplicateSubmissionIdentityError,
    build_application_idempotency_key,
    build_submission_identity_aliases,
    claim_submission_identity_aliases,
    find_existing_application_for_aliases,
)
from app.services.supervised_target_identity import (
    persist_supervised_target_metadata,
    resolve_supervised_target_metadata,
)


INTAKE_SOURCE = "manual_lever_phase_b_current"
SELECTION_POLICY = "user_selected_exact_application_no_ranking"


class CurrentLeverPhaseBIntakeError(ValueError):
    pass


def _required_text(value: Any, field: str, max_length: int) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise CurrentLeverPhaseBIntakeError(f"{field} is required")
    if len(cleaned) > max_length:
        raise CurrentLeverPhaseBIntakeError(
            f"{field} exceeds the {max_length}-character limit"
        )
    return cleaned


def _candidate_job(
    *,
    employer: str,
    role: str,
    application_url: str,
    location: Optional[str],
    source_reference: Optional[str],
) -> Job:
    return Job(
        external_id="pending-current-lever-phase-b",
        title=role,
        company=employer,
        location=location,
        url=application_url,
        source=JobSource.lever,
        status=JobStatus.queued,
        relevance_score=0.0,
        raw_data={
            "application_method": "external_url",
            "selected_apply_url": application_url,
            "selection_policy": SELECTION_POLICY,
            "selection_source": INTAKE_SOURCE,
            "source_reference": source_reference,
        },
    )


async def import_current_lever_phase_b_candidate(
    db: Session,
    user: User,
    *,
    employer: str,
    role: str,
    application_url: str,
    location: Optional[str] = None,
    notes: Optional[str] = None,
    source_reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Materialize one exact current Lever target without consequential authority."""

    employer_value = _required_text(employer, "employer", 255)
    role_value = _required_text(role, "role", 500)
    try:
        canonical_url = canonical_lever_application_url(application_url)
    except Exception as exc:
        raise CurrentLeverPhaseBIntakeError(str(exc)) from exc
    location_value = str(location or "").strip()[:255] or None
    notes_value = str(notes or "").strip() or None
    source_reference_value = str(source_reference or "").strip()[:500] or None

    probe = _candidate_job(
        employer=employer_value,
        role=role_value,
        application_url=canonical_url,
        location=location_value,
        source_reference=source_reference_value,
    )
    target = await resolve_supervised_target_metadata(probe)
    blockers = [str(item) for item in target.get("blockers") or [] if str(item)]
    if target.get("verified") is not True or blockers:
        reason = ", ".join(blockers) or "exact_target_identity_unverified"
        raise CurrentLeverPhaseBIntakeError(
            f"Current Lever target failed exact public metadata verification: {reason}"
        )
    if str(target.get("canonical_application_url") or "") != canonical_url:
        raise CurrentLeverPhaseBIntakeError(
            "Current Lever target canonical URL changed during verification"
        )

    site = _required_text(target.get("site"), "site", 100)
    posting_id = _required_text(target.get("posting_id"), "posting_id", 100)
    application_identity = f"lever:{site.casefold()}:{posting_id}"

    job = (
        db.query(Job)
        .filter(Job.external_id == application_identity)
        .order_by(Job.id.asc())
        .first()
    )
    created_job = job is None
    if job is None:
        job = _candidate_job(
            employer=employer_value,
            role=role_value,
            application_url=canonical_url,
            location=location_value,
            source_reference=source_reference_value,
        )
        job.external_id = application_identity
        db.add(job)
        db.flush()
    else:
        existing_url = canonical_lever_application_url(
            str((job.raw_data or {}).get("selected_apply_url") or job.url or "")
        )
        if existing_url != canonical_url:
            raise CurrentLeverPhaseBIntakeError(
                "Existing Lever job identity points at a different target"
            )
        if str(job.title or "").strip().casefold() != role_value.casefold():
            raise CurrentLeverPhaseBIntakeError(
                "Existing Lever job role does not match current official target"
            )
        if str(job.company or "").strip().casefold() != employer_value.casefold():
            raise CurrentLeverPhaseBIntakeError(
                "Existing Lever job employer does not match current selection"
            )
        raw = dict(job.raw_data or {})
        job.raw_data = {
            **raw,
            "application_method": "external_url",
            "selected_apply_url": canonical_url,
            "selection_policy": SELECTION_POLICY,
            "selection_source": INTAKE_SOURCE,
            "source_reference": source_reference_value
            if source_reference_value is not None
            else raw.get("source_reference"),
        }
        db.add(job)

    persist_supervised_target_metadata(job, target)
    db.flush()
    aliases = build_submission_identity_aliases(job, target_metadata=target)
    application = find_existing_application_for_aliases(db, user.id, aliases)
    if application is None:
        application = (
            db.query(Application)
            .filter(Application.user_id == user.id, Application.job_id == job.id)
            .order_by(Application.id.asc())
            .first()
        )

    created_application = application is None
    if application is None:
        application = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
            automation_state=ApplicationAutomationState.preparing.value,
            notes=notes_value,
        )
        db.add(application)
        db.flush()
        application.submission_idempotency_key = build_application_idempotency_key(
            user.id,
            aliases,
            fallback_job_id=job.id,
        )
        try:
            claim_submission_identity_aliases(db, application, aliases)
        except DuplicateSubmissionIdentityError as exc:
            raise CurrentLeverPhaseBIntakeError(str(exc)) from exc
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="lever_phase_b_current_candidate_imported",
                from_state=None,
                to_state=ApplicationAutomationState.preparing.value,
                payload={
                    "job_id": job.id,
                    "platform": "lever",
                    "adapter_version": target.get("adapter_version"),
                    "site": site,
                    "posting_id": posting_id,
                    "region": target.get("region"),
                    "target_identity_hash": target.get("identity_hash"),
                    "selection_policy": SELECTION_POLICY,
                    "selection_source": INTAKE_SOURCE,
                    "source_reference": source_reference_value,
                    "submission_queued": False,
                    "approval_issued": False,
                    "runtime_flags_changed": False,
                },
            )
        )
    elif application.job_id != job.id:
        raise CurrentLeverPhaseBIntakeError(
            "Exact Lever posting identity is already owned by another application"
        )

    return {
        "application_id": application.id,
        "job_id": job.id,
        "created_job": created_job,
        "created_application": created_application,
        "employer": job.company,
        "role": job.title,
        "application_url": canonical_url,
        "automation_state": application.automation_state,
        "selection_policy": SELECTION_POLICY,
        "target_identity_verified": True,
        "site": site,
        "posting_id": posting_id,
        "region": target.get("region"),
        "adapter_version": target.get("adapter_version"),
        "submission_queued": False,
        "approval_issued": False,
        "runtime_flags_changed": False,
    }


__all__ = [
    "CurrentLeverPhaseBIntakeError",
    "INTAKE_SOURCE",
    "SELECTION_POLICY",
    "import_current_lever_phase_b_candidate",
]
