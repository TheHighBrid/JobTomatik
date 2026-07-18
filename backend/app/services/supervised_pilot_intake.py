"""Preparation-only intake for one exact user-selected Greenhouse application.

This service creates a Job and Application record for review. It never enables
runtime flags, issues an approval, queues a worker, opens a browser, or performs
a submission.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlsplit, urlunsplit

from sqlalchemy.orm import Session

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User


INTAKE_SOURCE = "manual_greenhouse_phase_b"
SELECTION_POLICY = "user_selected_exact_application"


class SupervisedPilotIntakeError(ValueError):
    pass


def _required_text(value: str, field: str, max_length: int) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise SupervisedPilotIntakeError(f"{field} is required")
    if len(cleaned) > max_length:
        raise SupervisedPilotIntakeError(
            f"{field} exceeds the {max_length}-character limit"
        )
    return cleaned


def normalize_greenhouse_application_url(value: str) -> str:
    raw = _required_text(value, "application_url", 1000)
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise SupervisedPilotIntakeError("application_url is invalid") from exc

    if parsed.scheme.lower() != "https":
        raise SupervisedPilotIntakeError("application_url must use HTTPS")
    if parsed.username or parsed.password:
        raise SupervisedPilotIntakeError(
            "application_url must not contain embedded credentials"
        )

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or not (host == "greenhouse.io" or host.endswith(".greenhouse.io")):
        raise SupervisedPilotIntakeError(
            "application_url must be hosted on an official greenhouse.io domain"
        )
    if port not in (None, 443):
        raise SupervisedPilotIntakeError(
            "application_url must not use a non-standard port"
        )

    path = parsed.path or "/"
    query = parse_qs(parsed.query, keep_blank_values=True)
    identifies_job = (
        "/jobs/" in path.lower()
        or path.lower().endswith("/embed/job_app")
        or bool(query.get("gh_jid"))
        or bool(query.get("token"))
    )
    if not identifies_job:
        raise SupervisedPilotIntakeError(
            "application_url must identify one exact Greenhouse job"
        )

    netloc = host
    return urlunsplit(("https", netloc, path, parsed.query, ""))


def _target_digest(application_url: str) -> str:
    return hashlib.sha256(application_url.encode("utf-8")).hexdigest()


def import_supervised_pilot_candidate(
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
    """Create or return one preparation-only Phase B application record."""

    employer_value = _required_text(employer, "employer", 255)
    role_value = _required_text(role, "role", 500)
    normalized_url = normalize_greenhouse_application_url(application_url)
    location_value = str(location or "").strip()[:255] or None
    notes_value = str(notes or "").strip() or None
    source_reference_value = str(source_reference or "").strip()[:500] or None

    digest = _target_digest(normalized_url)
    external_id = f"greenhouse-phase-b-{digest[:32]}"
    idempotency_key = f"greenhouse-phase-b:{user.id}:{digest[:40]}"

    job = db.query(Job).filter(Job.external_id == external_id).first()
    created_job = job is None
    if job is None:
        job = Job(
            external_id=external_id,
            title=role_value,
            company=employer_value,
            location=location_value,
            url=normalized_url,
            source=JobSource.manual,
            status=JobStatus.queued,
            relevance_score=0.0,
            raw_data={
                "application_method": "external_url",
                "selected_apply_url": normalized_url,
                "selection_policy": SELECTION_POLICY,
                "selection_source": INTAKE_SOURCE,
                "source_reference": source_reference_value,
            },
        )
        db.add(job)
        db.flush()

    application = (
        db.query(Application)
        .filter(
            Application.user_id == user.id,
            Application.job_id == job.id,
        )
        .first()
    )
    if application is None:
        application = (
            db.query(Application)
            .filter(Application.submission_idempotency_key == idempotency_key)
            .first()
        )

    created_application = application is None
    if application is None:
        application = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
            automation_state=ApplicationAutomationState.preparing.value,
            submission_idempotency_key=idempotency_key,
            notes=notes_value,
        )
        db.add(application)
        db.flush()
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="supervised_pilot_candidate_imported",
                from_state=None,
                to_state=ApplicationAutomationState.preparing.value,
                payload={
                    "job_id": job.id,
                    "platform": "greenhouse",
                    "selection_policy": SELECTION_POLICY,
                    "selection_source": INTAKE_SOURCE,
                    "application_url_sha256": digest,
                    "source_reference": source_reference_value,
                    "submission_queued": False,
                    "approval_issued": False,
                    "runtime_flags_changed": False,
                },
            )
        )

    return {
        "application_id": application.id,
        "job_id": job.id,
        "created_job": created_job,
        "created_application": created_application,
        "employer": job.company,
        "role": job.title,
        "application_url": normalized_url,
        "automation_state": application.automation_state,
        "selection_policy": SELECTION_POLICY,
        "submission_queued": False,
        "approval_issued": False,
        "runtime_flags_changed": False,
    }


__all__ = [
    "INTAKE_SOURCE",
    "SELECTION_POLICY",
    "SupervisedPilotIntakeError",
    "import_supervised_pilot_candidate",
    "normalize_greenhouse_application_url",
]
