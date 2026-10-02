"""Worker-side Day 39 live-pilot enforcement immediately before browser submission."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.application import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewReason,
)
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.application_state import create_manual_review_task
from app.services.day39_live_runtime import reserve_canonical_day39_live_attempt


def enforce_day39_live_worker_gate(
    db,
    *,
    app: Application,
    job: Job,
    user: User,
    dry_run: bool,
    platform: str,
) -> dict[str, Any]:
    """Reserve live authority or convert the application to a safe manual-review hold.

    This function is intentionally called only after the ordinary production policy
    recheck. A successful reservation is committed before the consequential browser
    worker is invoked so a crash or uncertain outcome can never reclaim that slot.
    """

    if dry_run is not False:
        return {
            "allowed": True,
            "reason": "dry_run_not_subject_to_live_pilot_authority",
            "live_pilot_gate_applied": False,
        }

    reservation = reserve_canonical_day39_live_attempt(
        db,
        user_id=int(user.id),
        application_id=int(app.id),
        platform=platform,
    )
    if reservation.get("allowed") is True:
        db.add(
            ApplicationEvent(
                application_id=app.id,
                event_type="live_pilot_attempt_reserved",
                from_state=str(app.automation_state or ""),
                to_state=str(app.automation_state or ""),
                payload={
                    "source": "day39_live_worker_gate",
                    "authorization_id": reservation.get("authorization_id"),
                    "reservation_id": reservation.get("reservation_id"),
                    "reservation_reused": reservation.get("reused") is True,
                    "attempts_reserved": reservation.get("attempts_reserved"),
                    "attempt_cap": reservation.get("attempt_cap"),
                    "runtime_revision": reservation.get("runtime_revision"),
                    "non_reclaiming": True,
                },
            )
        )
        # The reservation is authority. Persist it before any browser work so process
        # death cannot make the same capacity appear available again.
        db.commit()
        return {
            "allowed": True,
            "success": True,
            "dry_run": False,
            "live_pilot_gate_applied": True,
            "reservation": reservation,
        }

    reason_code = str(reservation.get("reason") or "live_pilot_authority_missing")
    reason = f"Live pilot worker blocked before browser work: {reason_code}"
    log = [
        {
            "action": "live_pilot_worker_blocked",
            "reason_code": reason_code,
            "reason": reason,
            "ts": datetime.utcnow().isoformat(),
        }
    ]
    app.status = ApplicationStatus.pending
    app.automation_log = log
    create_manual_review_task(
        db,
        app,
        ManualReviewReason.safety_gate_blocked,
        reason,
        details={
            "unattended": True,
            "live_pilot": True,
            "reason_code": reason_code,
            "reservation": reservation,
        },
        blocking_url=job.url,
    )
    db.add(
        ApplicationEvent(
            application_id=app.id,
            event_type="live_pilot_worker_blocked",
            from_state=str(app.automation_state or ""),
            to_state=str(app.automation_state or ""),
            payload={
                "source": "day39_live_worker_gate",
                "reason_code": reason_code,
                "reservation": reservation,
            },
        )
    )
    db.add(
        Notification(
            user_id=user.id,
            type=NotificationType.system,
            title=f"Live pilot blocked: {job.title}",
            message=reason,
            data={
                "job_id": job.id,
                "application_id": app.id,
                "reason": reason_code,
                "live_pilot": True,
            },
        )
    )
    db.commit()
    return {
        "allowed": False,
        "success": False,
        "dry_run": False,
        "requires_manual_review": True,
        "error": reason_code,
        "policy_decision": {
            "allowed": False,
            "code": reason_code,
            "reason": reason,
            "metadata": {
                "live_pilot": True,
                "global_submit_flag_is_not_authority": True,
            },
        },
        "log": log,
    }


__all__ = ["enforce_day39_live_worker_gate"]
