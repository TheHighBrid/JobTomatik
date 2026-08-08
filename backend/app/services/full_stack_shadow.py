"""Durable full-stack unattended shadow sessions for Phase 10.

Unlike the tiny policy-only CI rehearsal, a full-stack shadow session invokes the
actual Phase 8 scheduler cycle. Discovery, ranking, preparation, dry-run application
work, human-boundary detection, operational observability, and reconciliation can
therefore execute through their production code paths while final submission stays
provably disabled.

The supervisor is intentionally split into short Celery cycles. A four-, eight-, or
24-hour session does not depend on one long-lived worker task and can survive worker
restarts as long as the durable session remains active and a later cycle resumes it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewTask,
)
from app.models.certification import ShadowRunCycle, ShadowRunSession
from app.models.intelligence import AgentRun
from app.models.user import User
from app.services.certification_scale import current_revision, ensure_aware
from app.services.operations_policy import operations_readiness_manifest
from app.services.scheduler_policy import normalize_scheduler_settings


SHADOW_SESSION_VERSION = "phase10-full-stack-shadow-v1"
TERMINAL_SESSION_STATES = {"completed", "failed", "cancelled"}
ACTIVE_SESSION_STATES = {"scheduled", "running", "settling", "stopping"}
MAX_SUBMISSION_ATTEMPTS_WITHOUT_REVIEW = 3


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _iso(value: datetime | None) -> str | None:
    aware = ensure_aware(value)
    return aware.isoformat() if aware else None


def _scheduler_settings(user: User) -> dict[str, Any]:
    automation = dict(user.automation_settings or {})
    return normalize_scheduler_settings(automation.get("scheduler"))


def full_stack_shadow_preflight(user: User) -> dict[str, Any]:
    """Return fail-closed runtime requirements without mutating user settings."""
    settings = get_settings()
    operations = operations_readiness_manifest()
    scheduler = _scheduler_settings(user)
    revision = current_revision()

    checks = {
        "candidate_revision_known": revision != "unknown",
        "real_submission_disabled": settings.allow_real_application_submit is False,
        "autopilot_enabled": bool(operations.get("autopilot_enabled")),
        "global_kill_switch_clear": not bool(operations.get("global_kill_switch")),
        "scheduler_auto_search_enabled": bool(scheduler.get("auto_search_enabled")),
        "scheduler_auto_apply_enabled": bool(scheduler.get("auto_apply_enabled")),
        "scheduler_dry_run_enabled": bool(scheduler.get("dry_run_mode", True)),
    }
    blockers = [key for key, value in checks.items() if not value]
    return {
        "ok": not blockers,
        "checks": checks,
        "blockers": blockers,
        "candidate_revision": revision,
        "scheduler": scheduler,
        "operations": {
            "autopilot_enabled": bool(operations.get("autopilot_enabled")),
            "global_kill_switch": bool(operations.get("global_kill_switch")),
            "disabled_platforms": list(operations.get("disabled_platforms") or []),
        },
        "runtime": {
            "allow_real_application_submit": bool(settings.allow_real_application_submit),
        },
    }


def _session_configuration(user: User, preflight: dict[str, Any]) -> dict[str, Any]:
    scheduler = dict(preflight.get("scheduler") or {})
    return {
        "version": SHADOW_SESSION_VERSION,
        "candidate_revision": preflight.get("candidate_revision"),
        "scheduler": scheduler,
        "operations": dict(preflight.get("operations") or {}),
        "runtime": dict(preflight.get("runtime") or {}),
        "invariants": {
            "actual_scheduler_cycle_required": True,
            "dry_run_mode_required": True,
            "real_submission_must_remain_disabled": True,
            "final_submit_allowed": False,
            "runtime_settings_are_not_mutated_by_shadow_supervisor": True,
        },
    }


def _baseline_snapshot(db: Session, user_id: int, now: datetime) -> dict[str, Any]:
    return {
        "captured_at": now.isoformat(),
        "application_count": db.query(Application).filter(Application.user_id == user_id).count(),
        "manual_review_count": (
            db.query(ManualReviewTask)
            .join(Application, ManualReviewTask.application_id == Application.id)
            .filter(Application.user_id == user_id)
            .count()
        ),
        "agent_run_count": db.query(AgentRun).filter(AgentRun.user_id == user_id).count(),
    }


def create_shadow_session(
    db: Session,
    *,
    user: User,
    requested_duration_seconds: int,
    cycle_interval_seconds: int,
    fault_plan: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> ShadowRunSession:
    current = ensure_aware(now) or utc_now()
    existing = (
        db.query(ShadowRunSession)
        .filter(
            ShadowRunSession.user_id == user.id,
            ShadowRunSession.status.in_(ACTIVE_SESSION_STATES),
        )
        .order_by(ShadowRunSession.id.desc())
        .first()
    )
    if existing is not None:
        raise ValueError(f"active_shadow_session_exists:{existing.id}")

    preflight = full_stack_shadow_preflight(user)
    if not preflight["ok"]:
        raise ValueError("shadow_preflight_blocked:" + ",".join(preflight["blockers"]))

    duration = max(60, int(requested_duration_seconds))
    interval = max(60, min(int(cycle_interval_seconds), 60 * 60))
    session = ShadowRunSession(
        user_id=user.id,
        candidate_revision=preflight["candidate_revision"],
        requested_duration_seconds=duration,
        cycle_interval_seconds=interval,
        status="scheduled",
        started_at=current,
        expected_end_at=current + timedelta(seconds=duration),
        last_heartbeat_at=current,
        final_submit_allowed=False,
        stop_requested=False,
        configuration_snapshot=_session_configuration(user, preflight),
        baseline_snapshot=_baseline_snapshot(db, user.id, current),
        fault_plan=dict(fault_plan or {}),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _observability_report(db: Session, user_id: int, *, window_hours: int) -> dict[str, Any]:
    try:
        from app.services.operational_observability import build_operational_observability_report

        return build_operational_observability_report(
            db,
            user_id,
            window_hours=max(1, min(int(window_hours), 24 * 30)),
        )
    except Exception as exc:
        return {
            "unavailable": True,
            "detail": str(exc)[:500],
            "summary": {"incident_count": 0, "critical_incident_count": 0},
            "incidents": [],
        }


def _cycle_application_ids(cycles: list[ShadowRunCycle]) -> list[int]:
    ids: list[int] = []
    for cycle in cycles:
        result = dict(cycle.scheduler_result or {})
        for action in result.get("actions") or []:
            if not isinstance(action, dict):
                continue
            application_id = action.get("application_id")
            if application_id is None:
                continue
            try:
                ids.append(int(application_id))
            except (TypeError, ValueError):
                continue
    return ids


def _reconcile_session(db: Session, session: ShadowRunSession) -> dict[str, Any]:
    cycles = (
        db.query(ShadowRunCycle)
        .filter(ShadowRunCycle.session_id == session.id)
        .order_by(ShadowRunCycle.cycle_number.asc(), ShadowRunCycle.id.asc())
        .all()
    )
    referenced_ids = _cycle_application_ids(cycles)
    unique_ids = sorted(set(referenced_ids))
    duplicate_ids = len(referenced_ids) - len(unique_ids)

    applications = []
    if unique_ids:
        applications = (
            db.query(Application)
            .filter(
                Application.user_id == session.user_id,
                Application.id.in_(unique_ids),
            )
            .all()
        )
    found = {int(app.id): app for app in applications}
    missing_ids = [application_id for application_id in unique_ids if application_id not in found]

    submitted_ids: list[int] = []
    ready_ids: list[int] = []
    human_ids: list[int] = []
    failed_ids: list[int] = []
    active_ids: list[int] = []
    runaway_ids: list[int] = []
    app_rows: list[dict[str, Any]] = []

    for application_id in unique_ids:
        app = found.get(application_id)
        if app is None:
            continue
        status_value = app.status.value if hasattr(app.status, "value") else str(app.status)
        automation_state = str(app.automation_state or "")
        if status_value == ApplicationStatus.submitted.value:
            submitted_ids.append(application_id)
        if automation_state == ApplicationAutomationState.ready_to_submit.value:
            ready_ids.append(application_id)
        if automation_state == ApplicationAutomationState.needs_human.value:
            human_ids.append(application_id)
        if automation_state == ApplicationAutomationState.failed.value:
            failed_ids.append(application_id)
        if automation_state in {
            ApplicationAutomationState.preparing.value,
            ApplicationAutomationState.applying.value,
        }:
            active_ids.append(application_id)
        if int(app.submission_attempt_count or 0) > MAX_SUBMISSION_ATTEMPTS_WITHOUT_REVIEW:
            runaway_ids.append(application_id)
        app_rows.append(
            {
                "application_id": application_id,
                "status": status_value,
                "automation_state": automation_state,
                "submission_attempt_count": int(app.submission_attempt_count or 0),
                "target_status": str(app.application_target_status or ""),
                "updated_at": _iso(app.updated_at or app.created_at),
            }
        )

    started = ensure_aware(session.started_at) or ensure_aware(session.created_at) or utc_now()
    end = ensure_aware(session.completed_at) or utc_now()
    discovery_runs = (
        db.query(AgentRun)
        .filter(
            AgentRun.user_id == session.user_id,
            AgentRun.created_at >= started,
            AgentRun.created_at <= end,
        )
        .all()
    )
    scheduler_discovery = [
        run
        for run in discovery_runs
        if (run.run_context or {}).get("origin") == "scheduler"
        or (run.run_context or {}).get("pipeline") == "public_ats_discovery_v1"
    ]
    discovered_saved = sum(int((run.result or {}).get("saved") or 0) for run in scheduler_discovery)
    discovered_total = sum(int((run.result or {}).get("total_found") or 0) for run in scheduler_discovery)

    events = []
    if unique_ids:
        events = (
            db.query(ApplicationEvent)
            .filter(
                ApplicationEvent.application_id.in_(unique_ids),
                ApplicationEvent.created_at >= started,
            )
            .order_by(ApplicationEvent.created_at.asc(), ApplicationEvent.id.asc())
            .all()
        )
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1

    unexplained = len(missing_ids)
    policy_escapes = []
    if submitted_ids:
        policy_escapes.append({
            "code": "shadow_submission_occurred",
            "application_ids": submitted_ids,
        })
    if session.final_submit_allowed:
        policy_escapes.append({"code": "shadow_final_submit_flag_changed"})

    return {
        "version": SHADOW_SESSION_VERSION,
        "session_id": session.id,
        "candidate_revision": session.candidate_revision,
        "started_at": _iso(session.started_at),
        "completed_at": _iso(session.completed_at),
        "requested_duration_seconds": session.requested_duration_seconds,
        "measured_duration_seconds": max(0.0, (end - started).total_seconds()),
        "cycle_count": len(cycles),
        "cycle_failures": sum(1 for cycle in cycles if cycle.status == "failed"),
        "scheduler_actions": len(referenced_ids),
        "unique_application_ids": unique_ids,
        "duplicate_application_references": duplicate_ids,
        "missing_application_ids": missing_ids,
        "applications": app_rows,
        "applications_ready_to_submit": ready_ids,
        "human_boundary_application_ids": human_ids,
        "failed_application_ids": failed_ids,
        "active_application_ids": active_ids,
        "runaway_retry_application_ids": runaway_ids,
        "submitted_application_ids": submitted_ids,
        "discovery": {
            "agent_runs": len(scheduler_discovery),
            "total_found": discovered_total,
            "saved": discovered_saved,
        },
        "application_events": event_counts,
        "unexplained_records": unexplained,
        "policy_escapes": policy_escapes,
        "reconciled": not missing_ids and not policy_escapes,
    }


def _build_final_report(
    db: Session,
    session: ShadowRunSession,
    *,
    status: str,
    failure_reason: str | None = None,
) -> dict[str, Any]:
    reconciliation = _reconcile_session(db, session)
    measured = float(reconciliation["measured_duration_seconds"])
    observability = _observability_report(
        db,
        session.user_id,
        window_hours=max(1, int(measured // 3600) + 1),
    )
    report = {
        "version": SHADOW_SESSION_VERSION,
        "session_id": session.id,
        "status": status,
        "candidate_revision": session.candidate_revision,
        "requested_duration_seconds": session.requested_duration_seconds,
        "measured_duration_seconds": measured,
        "measured_elapsed_time": True,
        "started_at": _iso(session.started_at),
        "completed_at": _iso(session.completed_at),
        "cycles_completed": session.cycles_completed,
        "cycles_failed": session.cycles_failed,
        "configuration_snapshot": dict(session.configuration_snapshot or {}),
        "fault_plan": dict(session.fault_plan or {}),
        "reconciliation": reconciliation,
        "observability": {
            "summary": dict(observability.get("summary") or {}),
            "activity": dict(observability.get("activity") or {}),
            "incidents": list(observability.get("incidents") or []),
            "unavailable": bool(observability.get("unavailable")),
        },
        "safety": {
            "final_submit_enabled": False,
            "final_submit_clicked": bool(reconciliation["submitted_application_ids"]),
            "real_submission_remained_disabled": not bool(
                (session.configuration_snapshot or {}).get("runtime", {}).get(
                    "allow_real_application_submit"
                )
            ),
            "dry_run_required": True,
            "runtime_settings_changed_by_supervisor": False,
        },
        "quality": {
            "no_leaked_or_missing_application_records": not bool(
                reconciliation["missing_application_ids"]
            ),
            "no_duplicate_scheduler_application_references": (
                reconciliation["duplicate_application_references"] == 0
            ),
            "no_false_submitted_status": not bool(reconciliation["submitted_application_ids"]),
            "no_runaway_retry": not bool(reconciliation["runaway_retry_application_ids"]),
            "no_policy_escape": not bool(reconciliation["policy_escapes"]),
        },
        "failure_reason": failure_reason,
    }
    report["qualification_eligible"] = (
        status == "completed"
        and measured >= session.requested_duration_seconds
        and all(report["quality"].values())
        and report["safety"]["final_submit_clicked"] is False
        and report["safety"]["real_submission_remained_disabled"] is True
    )
    report["report_sha256"] = canonical_hash(report)
    return report


def finalize_shadow_session(
    db: Session,
    session: ShadowRunSession,
    *,
    status: str,
    failure_reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = ensure_aware(now) or utc_now()
    session.status = status
    session.completed_at = current
    session.last_heartbeat_at = current
    session.failure_reason = failure_reason
    db.flush()
    report = _build_final_report(
        db,
        session,
        status=status,
        failure_reason=failure_reason,
    )
    reconciliation = dict(report.get("reconciliation") or {})
    session.applications_created = len(reconciliation.get("unique_application_ids") or [])
    session.applications_ready_to_submit = len(
        reconciliation.get("applications_ready_to_submit") or []
    )
    session.human_boundaries = len(
        reconciliation.get("human_boundary_application_ids") or []
    )
    session.unexplained_records = int(reconciliation.get("unexplained_records") or 0)
    session.duplicate_application_ids = int(
        reconciliation.get("duplicate_application_references") or 0
    )
    session.runaway_retry_count = len(
        reconciliation.get("runaway_retry_application_ids") or []
    )
    session.final_report = report
    session.report_sha256 = report["report_sha256"]
    db.commit()
    db.refresh(session)
    return report


def execute_shadow_cycle(
    db: Session,
    *,
    session_id: int,
    scheduler_runner: Callable[[Session, User], dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute one real scheduler cycle and return supervisor scheduling metadata."""
    current = ensure_aware(now) or utc_now()
    session = db.query(ShadowRunSession).filter(ShadowRunSession.id == session_id).first()
    if session is None:
        return {"status": "missing", "session_id": session_id, "schedule_next": False}
    if session.status in TERMINAL_SESSION_STATES:
        return {"status": session.status, "session_id": session.id, "schedule_next": False}
    if session.stop_requested or session.status == "stopping":
        report = finalize_shadow_session(
            db,
            session,
            status="cancelled",
            failure_reason="operator_stop_requested",
            now=current,
        )
        return {"status": "cancelled", "session_id": session.id, "schedule_next": False, "report": report}

    user = db.query(User).filter(User.id == session.user_id).first()
    if user is None:
        report = finalize_shadow_session(
            db,
            session,
            status="failed",
            failure_reason="shadow_user_missing",
            now=current,
        )
        return {"status": "failed", "session_id": session.id, "schedule_next": False, "report": report}

    preflight = full_stack_shadow_preflight(user)
    blockers = list(preflight.get("blockers") or [])
    if preflight.get("candidate_revision") != session.candidate_revision:
        blockers.append("candidate_revision_changed")
    if blockers:
        report = finalize_shadow_session(
            db,
            session,
            status="failed",
            failure_reason="shadow_preflight_changed:" + ",".join(sorted(set(blockers))),
            now=current,
        )
        return {"status": "failed", "session_id": session.id, "schedule_next": False, "report": report}

    if scheduler_runner is None:
        # Imported lazily to avoid task-registration cycles and to guarantee the
        # production path is the same scheduler used by Phase 8 unattended operation.
        from app.tasks.scraping import _run_scheduler_cycle_for_user

        scheduler_runner = _run_scheduler_cycle_for_user

    cycle_number = int(session.cycles_completed or 0) + int(session.cycles_failed or 0) + 1
    cycle = ShadowRunCycle(
        session_id=session.id,
        cycle_number=cycle_number,
        status="running",
        started_at=current,
        fault_injection={},
    )
    db.add(cycle)
    session.status = "running"
    session.last_heartbeat_at = current
    db.commit()
    db.refresh(cycle)

    try:
        result = scheduler_runner(db, user)
        if not isinstance(result, dict):
            result = {"raw_result": str(result)}
        cycle.scheduler_result = result
        window_hours = max(1, int(session.requested_duration_seconds // 3600) + 1)
        cycle.observability_snapshot = _observability_report(
            db,
            session.user_id,
            window_hours=window_hours,
        )
        cycle.reconciliation_snapshot = {
            "actions": len(result.get("actions") or []),
            "blockers": list(result.get("blockers") or []),
            "application_gate": result.get("application_gate"),
            "quiet_hours_active": bool(result.get("quiet_hours_active")),
            "dry_run": bool(result.get("dry_run", True)),
            "real_submission_enabled": bool(result.get("real_submission_enabled", False)),
        }
        if result.get("real_submission_enabled"):
            raise RuntimeError("shadow_scheduler_reported_real_submission_enabled")
        if result.get("dry_run") is False:
            raise RuntimeError("shadow_scheduler_reported_dry_run_false")
        cycle.status = "completed"
        cycle.completed_at = utc_now()
        session.cycles_completed = int(session.cycles_completed or 0) + 1
        session.last_cycle_at = cycle.completed_at
        session.last_heartbeat_at = cycle.completed_at
        db.commit()
    except Exception as exc:
        db.rollback()
        cycle = db.query(ShadowRunCycle).filter(ShadowRunCycle.id == cycle.id).first()
        session = db.query(ShadowRunSession).filter(ShadowRunSession.id == session.id).first()
        detail = str(exc)[:1800]
        if cycle is not None:
            cycle.status = "failed"
            cycle.completed_at = utc_now()
            cycle.error_detail = detail
        if session is not None:
            session.cycles_failed = int(session.cycles_failed or 0) + 1
            session.last_cycle_at = utc_now()
            session.last_heartbeat_at = session.last_cycle_at
        db.commit()
        # A cycle failure is observed and retried on the next bounded cycle. Three
        # consecutive failed cycles terminate the session rather than retry forever.
        recent = (
            db.query(ShadowRunCycle)
            .filter(ShadowRunCycle.session_id == session_id)
            .order_by(ShadowRunCycle.cycle_number.desc(), ShadowRunCycle.id.desc())
            .limit(3)
            .all()
        )
        if len(recent) >= 3 and all(item.status == "failed" for item in recent):
            session = db.query(ShadowRunSession).filter(ShadowRunSession.id == session_id).first()
            report = finalize_shadow_session(
                db,
                session,
                status="failed",
                failure_reason="three_consecutive_shadow_cycle_failures",
            )
            return {"status": "failed", "session_id": session_id, "schedule_next": False, "report": report}

    session = db.query(ShadowRunSession).filter(ShadowRunSession.id == session_id).first()
    started = ensure_aware(session.started_at) or current
    measured = max(0.0, (utc_now() - started).total_seconds())
    if measured >= int(session.requested_duration_seconds):
        report = finalize_shadow_session(db, session, status="completed")
        if not report.get("qualification_eligible"):
            # Duration alone never converts reconciliation defects into success.
            session = db.query(ShadowRunSession).filter(ShadowRunSession.id == session_id).first()
            session.status = "failed"
            session.failure_reason = "shadow_reconciliation_quality_gate_failed"
            session.final_report = _build_final_report(
                db,
                session,
                status="failed",
                failure_reason=session.failure_reason,
            )
            session.report_sha256 = session.final_report.get("report_sha256")
            db.commit()
            return {"status": "failed", "session_id": session_id, "schedule_next": False, "report": session.final_report}
        return {"status": "completed", "session_id": session_id, "schedule_next": False, "report": report}

    return {
        "status": "running",
        "session_id": session.id,
        "schedule_next": True,
        "countdown_seconds": int(session.cycle_interval_seconds),
        "measured_duration_seconds": measured,
        "requested_duration_seconds": int(session.requested_duration_seconds),
    }


def shadow_session_status(db: Session, *, session: ShadowRunSession) -> dict[str, Any]:
    started = ensure_aware(session.started_at)
    completed = ensure_aware(session.completed_at)
    measured = 0.0
    if started is not None:
        measured = max(0.0, ((completed or utc_now()) - started).total_seconds())
    cycles = (
        db.query(ShadowRunCycle)
        .filter(ShadowRunCycle.session_id == session.id)
        .order_by(ShadowRunCycle.cycle_number.desc(), ShadowRunCycle.id.desc())
        .limit(20)
        .all()
    )
    return {
        "session_id": session.id,
        "status": session.status,
        "candidate_revision": session.candidate_revision,
        "requested_duration_seconds": session.requested_duration_seconds,
        "measured_duration_seconds": measured,
        "cycle_interval_seconds": session.cycle_interval_seconds,
        "started_at": _iso(session.started_at),
        "expected_end_at": _iso(session.expected_end_at),
        "completed_at": _iso(session.completed_at),
        "last_cycle_at": _iso(session.last_cycle_at),
        "last_heartbeat_at": _iso(session.last_heartbeat_at),
        "cycles_completed": session.cycles_completed,
        "cycles_failed": session.cycles_failed,
        "stop_requested": bool(session.stop_requested),
        "final_submit_allowed": bool(session.final_submit_allowed),
        "applications_created": session.applications_created,
        "applications_ready_to_submit": session.applications_ready_to_submit,
        "human_boundaries": session.human_boundaries,
        "unexplained_records": session.unexplained_records,
        "duplicate_application_ids": session.duplicate_application_ids,
        "runaway_retry_count": session.runaway_retry_count,
        "failure_reason": session.failure_reason,
        "configuration_snapshot": dict(session.configuration_snapshot or {}),
        "fault_plan": dict(session.fault_plan or {}),
        "report_sha256": session.report_sha256,
        "final_report": dict(session.final_report or {}),
        "recent_cycles": [
            {
                "cycle_id": cycle.id,
                "cycle_number": cycle.cycle_number,
                "status": cycle.status,
                "started_at": _iso(cycle.started_at),
                "completed_at": _iso(cycle.completed_at),
                "scheduler_result": dict(cycle.scheduler_result or {}),
                "reconciliation_snapshot": dict(cycle.reconciliation_snapshot or {}),
                "error_detail": cycle.error_detail,
            }
            for cycle in cycles
        ],
    }


__all__ = [
    "ACTIVE_SESSION_STATES",
    "SHADOW_SESSION_VERSION",
    "TERMINAL_SESSION_STATES",
    "create_shadow_session",
    "execute_shadow_cycle",
    "finalize_shadow_session",
    "full_stack_shadow_preflight",
    "shadow_session_status",
]
