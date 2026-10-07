"""Fail-closed reconciliation for a restarted OneHost Celery worker."""

# Production OneHost intentionally runs without Celery Beat during the first rollout.
# A worker restart therefore needs one synchronous reconciliation pass before it may
# accept new work. The pass never retries a live final action. It uses the canonical
# application recovery service and invalidates only handoffs that were already in the
# worker-owned resuming state when the worker disappeared.

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.services.application_recovery import recover_interrupted_application_attempts
from app.services.handoff_session import fail_handoff_resume


WORKER_RESTART_HANDOFF_REASON = (
    "The OneHost worker restarted while this retained-browser handoff was resuming. "
    "The outcome requires reconciliation before any new final action."
)


def reconcile_onehost_worker_restart(db: Session) -> Dict[str, Any]:
    """Reconcile worker-owned in-flight state after a OneHost worker restart."""
    resuming = (
        db.query(ManualHandoffSession)
        .filter(ManualHandoffSession.status == HandoffSessionStatus.resuming.value)
        .with_for_update()
        .order_by(ManualHandoffSession.id.asc())
        .all()
    )

    failed_handoffs: list[str] = []
    for session in resuming:
        fail_handoff_resume(
            db,
            session,
            reason=WORKER_RESTART_HANDOFF_REASON,
            retryable=False,
        )
        failed_handoffs.append(session.public_id)

    application_recovery = recover_interrupted_application_attempts(db)

    return {
        "worker_restart_reconciled": True,
        "resuming_handoffs_checked": len(resuming),
        "resuming_handoffs_failed": len(failed_handoffs),
        "failed_handoff_public_ids": failed_handoffs,
        "application_recovery": application_recovery,
        "automatic_live_retry_performed": False,
        "submission_authorized": False,
    }


__all__ = [
    "WORKER_RESTART_HANDOFF_REASON",
    "reconcile_onehost_worker_restart",
]
