from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import Application, ApplicationEvent
from app.models.certification import ShadowRunCycle, ShadowRunSession
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services.certification_scale import ensure_aware
from app.services.full_stack_shadow import (
    ACTIVE_SESSION_STATES,
    execute_shadow_cycle,
    finalize_shadow_session,
    mark_shadow_dispatch_failure,
)
from app.services.operations_settings import get_operations_settings
from app.services.runtime_identity import runtime_identity_manifest


logger = logging.getLogger(__name__)

APPLICATION_PATH_WATCHDOG_GRACE_SECONDS = 60 * 60
APPLICATION_PATH_WATCHDOG_MIN_COMPLETED_CYCLES = 4
SHADOW_REUSABLE_APPROVED_LIMIT = 100
SHADOW_QUEUED_CANDIDATE_LIMIT = 400


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _autopilot_enabled() -> bool:
    return bool(get_operations_settings().autopilot_enabled)


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


def _prepare_shadow_candidate_cohort(db, session: ShadowRunSession) -> User | None:
    """Attach a transient, no-submit candidate cohort for one timed shadow cycle.

    Normal scheduler ranking intentionally sees only queued jobs. Timed shadow evidence
    needs a different test-only behavior: a posting already exercised by an earlier
    shadow session may be reused without treating that historical no-submit attempt as a
    production duplicate. Only jobs carrying the durable full-stack-shadow application
    event are eligible for this reuse. Production-approved jobs are never added.

    The existing transient candidate projection is deliberately process-local and is
    removed immediately after the cycle. This keeps persisted user policy unchanged.
    """

    user = (
        db.query(User)
        .filter(User.id == int(session.user_id), User.is_active == True)
        .first()
    )
    if user is None:
        return None

    queued_ids = [
        int(row[0])
        for row in (
            db.query(Job.id)
            .filter(Job.status == JobStatus.queued)
            .order_by(Job.relevance_score.desc(), Job.id.desc())
            .limit(SHADOW_QUEUED_CANDIDATE_LIMIT)
            .all()
        )
    ]

    reusable_job_ids: list[int] = []
    seen_reusable: set[int] = set()
    event_rows = (
        db.query(Application.job_id, ApplicationEvent.payload)
        .join(ApplicationEvent, ApplicationEvent.application_id == Application.id)
        .filter(
            Application.user_id == int(session.user_id),
            ApplicationEvent.event_type == "application_created",
        )
        .order_by(ApplicationEvent.id.desc())
        .limit(2000)
        .all()
    )
    for job_id, payload in event_rows:
        data = dict(payload or {})
        if str(data.get("source") or "") != "full_stack_shadow_scheduler":
            continue
        try:
            prior_session_id = int(data.get("shadow_session_id"))
        except (TypeError, ValueError):
            continue
        if prior_session_id == int(session.id):
            continue
        parsed_job_id = int(job_id)
        if parsed_job_id in seen_reusable:
            continue
        seen_reusable.add(parsed_job_id)
        reusable_job_ids.append(parsed_job_id)
        if len(reusable_job_ids) >= SHADOW_REUSABLE_APPROVED_LIMIT:
            break

    approved_shadow_ids: list[int] = []
    if reusable_job_ids:
        approved_shadow_ids = [
            int(row[0])
            for row in (
                db.query(Job.id)
                .filter(
                    Job.id.in_(reusable_job_ids),
                    Job.status == JobStatus.approved,
                )
                .order_by(Job.relevance_score.desc(), Job.id.desc())
                .all()
            )
        ]

    cohort: list[int] = []
    seen: set[int] = set()
    for job_id in [*approved_shadow_ids, *queued_ids]:
        if job_id in seen:
            continue
        seen.add(job_id)
        cohort.append(job_id)

    setattr(user, "_qualification_candidate_job_ids", tuple(cohort))
    return user


def _clear_shadow_candidate_cohort(user: User | None) -> None:
    if user is not None and hasattr(user, "_qualification_candidate_job_ids"):
        delattr(user, "_qualification_candidate_job_ids")


def _shadow_application_reference_count(db, session_id: int) -> int:
    cycles = (
        db.query(ShadowRunCycle)
        .filter(ShadowRunCycle.session_id == int(session_id))
        .order_by(ShadowRunCycle.cycle_number.asc(), ShadowRunCycle.id.asc())
        .all()
    )
    application_ids: set[int] = set()
    for cycle in cycles:
        result = dict(cycle.scheduler_result or {})
        for raw in result.get("application_ids_queued") or []:
            try:
                application_ids.add(int(raw))
            except (TypeError, ValueError):
                continue
    return len(application_ids)


def _apply_early_application_path_watchdog(db, result: dict, session_id: int) -> dict:
    """Fail a doomed long campaign after one healthy hour instead of at hour 8/24."""

    if result.get("status") != "running" or not result.get("schedule_next"):
        return result

    session = (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.id == int(session_id))
        .first()
    )
    if session is None or session.status not in ACTIVE_SESSION_STATES:
        return result

    current = _utc_now()
    started = ensure_aware(session.started_at) or current
    elapsed_seconds = max(0.0, (current - started).total_seconds())
    completed_cycles = int(session.cycles_completed or 0)
    if (
        elapsed_seconds < APPLICATION_PATH_WATCHDOG_GRACE_SECONDS
        or completed_cycles < APPLICATION_PATH_WATCHDOG_MIN_COMPLETED_CYCLES
    ):
        return result

    application_references = _shadow_application_reference_count(db, int(session.id))
    session.applications_created = application_references
    if application_references > 0:
        return result

    reason = "shadow_application_path_not_observed_after_1h"
    report = finalize_shadow_session(
        db,
        session,
        requested_status="failed",
        failure_reason=reason,
        now=current,
    )
    return {
        "status": "failed",
        "session_id": int(session.id),
        "schedule_next": False,
        "error": reason,
        "early_quality_gate": "application_path_observed",
        "cycles_completed": completed_cycles,
        "cycles_failed": int(session.cycles_failed or 0),
        "application_references": 0,
        "report": report,
        "submission_authorized": False,
        "outreach_authorized": False,
    }


def _attach_due_day37_incident(db, result: dict, session_id: int) -> dict:
    """Retain one due Day 37 incident without changing shadow-cycle qualification state."""

    if result.get("status") != "running" or not result.get("schedule_next"):
        return result

    session = (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.id == int(session_id))
        .first()
    )
    if session is None or str(session.target_evidence_type or "") != "shadow_run_8h":
        return result

    from app.services.day37_shadow_incidents import run_due_day37_incident

    incident = run_due_day37_incident(db, session)
    if incident is None:
        return result

    cycle = (
        db.query(ShadowRunCycle)
        .filter(
            ShadowRunCycle.session_id == int(session_id),
            ShadowRunCycle.status == "completed",
        )
        .order_by(ShadowRunCycle.cycle_number.desc(), ShadowRunCycle.id.desc())
        .first()
    )
    if cycle is None:
        logger.error("Day 37 incident had no completed cycle container session=%s", session_id)
        return result

    observability = dict(cycle.observability_snapshot or {})
    observability["day37_incident"] = incident
    cycle.observability_snapshot = observability
    result["day37_incident"] = {
        "incident_type": incident.get("incident_type"),
        "status": incident.get("status"),
        "recovery_contract": incident.get("recovery_contract"),
    }
    db.flush()
    return result


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
    prepared_user: User | None = None
    try:
        session = (
            db.query(ShadowRunSession)
            .filter(ShadowRunSession.id == int(session_id))
            .first()
        )
        if session is not None and session.status in ACTIVE_SESSION_STATES:
            prepared_user = _prepare_shadow_candidate_cohort(db, session)

        result = execute_shadow_cycle(db, session_id=int(session_id))
        result = _apply_early_application_path_watchdog(db, result, int(session_id))
        result = _attach_due_day37_incident(db, result, int(session_id))
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
        _clear_shadow_candidate_cohort(prepared_user)
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
