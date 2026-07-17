"""Fail-closed recovery for application attempts abandoned in ``applying``.

A worker can disappear after the lifecycle is moved to ``applying``. Leaving the
row there forever blocks every future attempt. Recovery never assumes that a
live submission did or did not complete. Dry-run interruptions route to manual
review; live or unknown interruptions route to ``submission_uncertain``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewReason,
)
from app.models.notification import Notification, NotificationType
from app.services.application_state import create_manual_review_task, normalize_state
from app.services.operations_settings import get_operations_settings


RECOVERY_KIND = "stale_application_attempt"


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _latest_attempt_event(db, application_id: int) -> ApplicationEvent | None:
    return (
        db.query(ApplicationEvent)
        .filter(
            ApplicationEvent.application_id == application_id,
            ApplicationEvent.event_type == "application_attempt_started",
        )
        .order_by(ApplicationEvent.created_at.desc(), ApplicationEvent.id.desc())
        .first()
    )


def _attempt_dry_run(db, application: Application) -> bool | None:
    event = _latest_attempt_event(db, application.id)
    if not event:
        return None
    value = (event.payload or {}).get("dry_run")
    return value if isinstance(value, bool) else None


def recover_stale_application_attempt(
    db,
    application: Application,
    *,
    now: datetime | None = None,
    timeout_minutes: int | None = None,
) -> Dict[str, Any]:
    """Recover one stale attempt while preserving duplicate-prevention safety."""

    normalized_now = _naive_utc(now or datetime.utcnow()) or datetime.utcnow()
    timeout = max(
        5,
        int(timeout_minutes or get_operations_settings().stale_attempt_minutes),
    )
    state = normalize_state(application.automation_state)
    if state != ApplicationAutomationState.applying.value:
        return {
            "application_id": application.id,
            "recovered": False,
            "reason": "not_applying",
            "state": state,
        }

    started_at = _naive_utc(
        application.last_submission_attempt_at
        or application.updated_at
        or application.created_at
    )
    if started_at is None:
        return {
            "application_id": application.id,
            "recovered": False,
            "reason": "attempt_timestamp_missing",
            "state": state,
        }

    age_seconds = max(0, int((normalized_now - started_at).total_seconds()))
    if age_seconds < timeout * 60:
        return {
            "application_id": application.id,
            "recovered": False,
            "reason": "attempt_still_fresh",
            "state": state,
            "age_seconds": age_seconds,
            "timeout_minutes": timeout,
        }

    dry_run = _attempt_dry_run(db, application)
    job = application.job
    blocking_url = getattr(job, "url", None)
    job_title = getattr(job, "title", None) or f"Application {application.id}"

    if dry_run is True:
        target_state = ApplicationAutomationState.needs_review
        reason_code = ManualReviewReason.automation_error
        summary = (
            "A dry-run application attempt stopped before reaching a verified "
            "terminal state. Review the retained evidence before retrying."
        )
    else:
        target_state = ApplicationAutomationState.submission_uncertain
        reason_code = ManualReviewReason.submission_confirmation_uncertain
        summary = (
            "An application worker stopped during a live or unknown submission "
            "attempt. Verify the employer portal before any retry."
        )

    details = {
        "kind": RECOVERY_KIND,
        "dry_run": dry_run,
        "attempt_age_seconds": age_seconds,
        "timeout_minutes": timeout,
        "submission_attempt_count": int(application.submission_attempt_count or 0),
        "idempotency_key": application.submission_idempotency_key,
        "recovered_at": normalized_now.replace(microsecond=0).isoformat() + "Z",
    }
    review = create_manual_review_task(
        db,
        application,
        reason_code,
        summary,
        details=details,
        blocking_url=blocking_url,
        target_state=target_state,
    )
    application.status = ApplicationStatus.pending
    db.add(ApplicationEvent(
        application_id=application.id,
        event_type="stale_application_attempt_recovered",
        from_state=normalize_state(application.automation_state),
        to_state=normalize_state(application.automation_state),
        payload={
            **details,
            "reason_code": reason_code.value,
            "review_id": review.id,
        },
    ))
    db.add(Notification(
        user_id=application.user_id,
        type=NotificationType.system,
        title=f"Application attempt recovered: {job_title}",
        message=summary,
        data={
            "kind": RECOVERY_KIND,
            "application_id": application.id,
            "job_id": application.job_id,
            "review_id": review.id,
            "reason": reason_code.value,
            "dry_run": dry_run,
        },
    ))
    return {
        "application_id": application.id,
        "recovered": True,
        "dry_run": dry_run,
        "reason_code": reason_code.value,
        "target_state": normalize_state(application.automation_state),
        "review_id": review.id,
        "age_seconds": age_seconds,
        "timeout_minutes": timeout,
    }


def recover_stale_application_attempts(
    db,
    *,
    now: datetime | None = None,
    timeout_minutes: int | None = None,
) -> Dict[str, Any]:
    """Recover every stale ``applying`` row in a single transaction scope."""

    normalized_now = _naive_utc(now or datetime.utcnow()) or datetime.utcnow()
    timeout = max(
        5,
        int(timeout_minutes or get_operations_settings().stale_attempt_minutes),
    )
    cutoff = normalized_now - timedelta(minutes=timeout)
    applications = (
        db.query(Application)
        .filter(
            Application.automation_state == ApplicationAutomationState.applying.value,
            Application.last_submission_attempt_at.isnot(None),
            Application.last_submission_attempt_at <= cutoff,
        )
        .with_for_update()
        .all()
    )

    results = [
        recover_stale_application_attempt(
            db,
            application,
            now=normalized_now,
            timeout_minutes=timeout,
        )
        for application in applications
    ]
    recovered = [item for item in results if item.get("recovered")]
    return {
        "checked": len(applications),
        "recovered": len(recovered),
        "dry_run_recovered": sum(item.get("dry_run") is True for item in recovered),
        "uncertain_recovered": sum(item.get("dry_run") is not True for item in recovered),
        "timeout_minutes": timeout,
        "applications": results,
    }


__all__ = [
    "RECOVERY_KIND",
    "recover_stale_application_attempt",
    "recover_stale_application_attempts",
]
