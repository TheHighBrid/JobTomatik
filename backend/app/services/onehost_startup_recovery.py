"""Fail-closed reconciliation for a restarted OneHost Celery worker."""

# Production OneHost intentionally runs without Celery Beat during the first rollout.
# A worker restart therefore needs one synchronous reconciliation pass before it may
# accept new work. The pass never retries a live final action. It uses the canonical
# application recovery service and invalidates only handoffs that were already in the
# worker-owned resuming state when the worker disappeared.

from __future__ import annotations

from typing import Any, Dict
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.handoff import HandoffSessionStatus, HandoffChallengeType, ManualHandoffSession, HandoffSessionEvent
from app.services.application_recovery import recover_interrupted_application_attempts
from app.services.handoff_session import fail_handoff_resume, handoff_utc
from app.services.jt5_reconciliation import reconcile_stale_jt5_attempts


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

    # A backend-container restart also retires its shared PID namespace. Never
    # present a dead final-submit browser as an active owner handoff afterwards.
    retained = db.query(ManualHandoffSession).filter(
        ManualHandoffSession.challenge_type == HandoffChallengeType.final_submit.value,
        ManualHandoffSession.status.in_(["awaiting_user", "claimed"]),
        ManualHandoffSession.browser_provider == "local_cdp",
    ).with_for_update().all()
    unavailable = []
    from app.services.browser_runtime_base import current_browser_node_id
    for session in retained:
        if session.browser_node_id and session.browser_node_id != current_browser_node_id():
            continue
        alive = False
        try:
            pid = int(session.browser_process_id or 0)
            args = Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
            alive = pid > 1 and bool(session.browser_profile_path) and f"--user-data-dir={session.browser_profile_path}" in args
        except (OSError, ValueError):
            pass
        expired = handoff_utc(session.expires_at) <= datetime.utcnow()
        if alive and not expired:
            continue
        session.status = "expired" if expired else "failed"
        session.failure_reason = "The retained browser session expired or its process stopped. Preserve its evidence and reconcile before any new final action."
        session.lease_expires_at = None
        session.lock_version = (session.lock_version or 0) + 1
        unavailable.append(session.public_id)
        db.add(HandoffSessionEvent(
            handoff_session_id=session.id, application_id=session.application_id,
            event_type="handoff_browser_unavailable", actor_type="system",
            payload={"browser_process_alive": alive, "expired": expired, "automatic_retry_allowed": False},
        ))

    # Beat is absent on OneHost. Drain JT5 recovery batches before accepting
    # messages, including fresh claims owned by the worker that just stopped.
    # Keep this in the caller's transaction so a later startup failure rolls back.
    jt5_references: list[str] = []
    while True:
        batch = reconcile_stale_jt5_attempts(
            db, worker_restarted=True, commit=False,
        )
        if not batch:
            break
        jt5_references.extend(batch)

    application_recovery = recover_interrupted_application_attempts(db)

    return {
        "worker_restart_reconciled": True,
        "resuming_handoffs_checked": len(resuming),
        "resuming_handoffs_failed": len(failed_handoffs),
        "failed_handoff_public_ids": failed_handoffs,
        "unavailable_owner_handoffs": unavailable,
        "application_recovery": application_recovery,
        "jt5_attempts_reconciled": len(jt5_references),
        "jt5_attempt_references": jt5_references,
        "automatic_live_retry_performed": False,
        "submission_authorized": False,
    }


__all__ = [
    "WORKER_RESTART_HANDOFF_REASON",
    "reconcile_onehost_worker_restart",
]
