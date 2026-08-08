from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.certification import ShadowRunSession
from app.services.certification_scale import ensure_aware
from app.services.full_stack_shadow import (
    ACTIVE_SESSION_STATES,
    execute_shadow_cycle,
    mark_shadow_dispatch_failure,
)
from app.services.runtime_identity import runtime_identity_manifest


logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _autopilot_enabled() -> bool:
    return str(os.getenv("AUTOPILOT_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _identity_allows_shadow_execution() -> tuple[bool, dict]:
    identity = runtime_identity_manifest()
    if not _autopilot_enabled():
        return True, identity
    return bool(identity.get("deployment_attested")), identity


def _fail_session_for_identity(session_id: int, identity: dict) -> dict:
    db = SessionLocal()
    try:
        mark_shadow_dispatch_failure(
            db,
            session_id=int(session_id),
            detail="runtime_identity_unattested",
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist shadow runtime identity failure")
    finally:
        db.close()
    return {
        "session_id": int(session_id),
        "status": "failed",
        "error": "runtime_identity_unattested",
        "runtime_revision": identity.get("revision"),
        "runtime_role": identity.get("role"),
        "schedule_next": False,
        "submission_authorized": False,
        "outreach_authorized": False,
    }


@celery_app.task(
    name="app.tasks.shadow_runs.run_shadow_session_cycle",
    queue="scraping",
)
def run_shadow_session_cycle(session_id: int):
    """Run one bounded campaign cycle and schedule the next durable checkpoint."""

    identity_ok, identity = _identity_allows_shadow_execution()
    if not identity_ok:
        logger.error(
            "Shadow campaign runtime identity unattested session=%s role=%s revision=%s",
            session_id,
            identity.get("role"),
            identity.get("revision"),
        )
        return _fail_session_for_identity(int(session_id), identity)

    db = SessionLocal()
    try:
        result = execute_shadow_cycle(db, session_id=int(session_id))
        db.commit()
    except Exception:
        logger.exception("Shadow campaign cycle failed for session %s", session_id)
        db.rollback()
        try:
            mark_shadow_dispatch_failure(
                db,
                session_id=int(session_id),
                detail="cycle_supervisor_failure",
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to persist shadow campaign supervisor failure")
        return {
            "session_id": int(session_id),
            "status": "failed",
            "error": "cycle_supervisor_failure",
            "schedule_next": False,
        }
    finally:
        db.close()

    result["runtime_identity"] = identity
    if result.get("schedule_next"):
        countdown = max(1, int(result.get("countdown_seconds") or 60))
        try:
            task = run_shadow_session_cycle.apply_async(
                args=[int(session_id)],
                countdown=countdown,
            )
            result["next_cycle_task_id"] = task.id
            result["next_cycle_countdown_seconds"] = countdown
        except Exception:
            logger.exception("Failed to schedule next shadow campaign cycle")
            result["next_cycle_dispatch_error"] = "worker_dispatch_unavailable"
    return result


@celery_app.task(
    name="app.tasks.shadow_runs.recover_stalled_shadow_sessions",
    queue="scraping",
)
def recover_stalled_shadow_sessions():
    """Re-dispatch active sessions whose heartbeat stopped advancing.

    The actual cycle service performs a second row-locked running-cycle check, so a
    recovery dispatch cannot silently create a concurrent duplicate cycle.
    """

    db = SessionLocal()
    current = _utc_now()
    try:
        sessions = (
            db.query(ShadowRunSession)
            .filter(ShadowRunSession.status.in_(ACTIVE_SESSION_STATES))
            .order_by(ShadowRunSession.id.asc())
            .all()
        )
        candidates: list[int] = []
        for session in sessions:
            heartbeat = ensure_aware(session.last_heartbeat_at) or ensure_aware(session.started_at)
            timeout_seconds = max(1800, int(session.cycle_interval_seconds or 0) * 2)
            if heartbeat is None or (current - heartbeat).total_seconds() >= timeout_seconds:
                candidates.append(int(session.id))
        db.commit()
    finally:
        db.close()

    identity_ok, identity = _identity_allows_shadow_execution()
    dispatched: list[dict] = []
    for session_id in candidates:
        if not identity_ok:
            _fail_session_for_identity(session_id, identity)
            dispatched.append(
                {
                    "session_id": session_id,
                    "task_id": None,
                    "error": "runtime_identity_unattested",
                }
            )
            continue
        try:
            task = run_shadow_session_cycle.delay(session_id)
            dispatched.append({"session_id": session_id, "task_id": task.id})
        except Exception:
            logger.exception("Failed to redispatch stalled shadow campaign %s", session_id)
            dispatched.append(
                {
                    "session_id": session_id,
                    "task_id": None,
                    "error": "worker_dispatch_unavailable",
                }
            )
    return {
        "active_sessions_checked": len(sessions),
        "stalled_sessions": len(candidates),
        "dispatches": dispatched,
        "runtime_identity": identity,
        "submission_authorized": False,
        "outreach_authorized": False,
    }
