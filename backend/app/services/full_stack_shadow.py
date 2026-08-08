"""Durable full-stack no-submit campaigns for real certification evidence.

Phase 10 can evaluate shadow evidence. Phase 11 creates that evidence by repeatedly
exercising the production scheduler while real submission stays disabled. The service
never changes runtime controls, adapter maturity, outreach permissions, or release
authorization.
"""

from __future__ import annotations

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
from app.models.certification import (
    CertificationEvidence,
    ShadowRunCycle,
    ShadowRunSession,
)
from app.models.intelligence import AgentRun
from app.models.user import User
from app.services.certification_scale import (
    canonical_hash,
    current_revision,
    ensure_aware,
    evidence_key_for,
    evidence_payload,
)
from app.services.operations_policy import operations_readiness_manifest
from app.services.scheduler_policy import scheduler_settings


SHADOW_CAMPAIGN_VERSION = "phase11-full-stack-shadow-v1"
TARGET_SECONDS = {
    "shadow_run_4h": 4 * 60 * 60,
    "shadow_run_8h": 8 * 60 * 60,
    "shadow_run_24h": 24 * 60 * 60,
}
ACTIVE_SESSION_STATES = {"scheduled", "running", "settling", "stopping"}
TERMINAL_SESSION_STATES = {"completed", "failed", "cancelled"}
SETTLE_WINDOW_SECONDS = 45 * 60
MIN_CYCLE_INTERVAL_SECONDS = 60
MAX_CYCLE_INTERVAL_SECONDS = 60 * 60
DEFAULT_CYCLE_INTERVAL_SECONDS = 15 * 60
MAX_SUBMISSION_ATTEMPTS_WITHOUT_REVIEW = 3


class ShadowCampaignError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    aware = ensure_aware(value)
    return aware.replace(microsecond=0).isoformat() if aware else None


def _bounded_interval(value: int | None) -> int:
    requested = int(value or DEFAULT_CYCLE_INTERVAL_SECONDS)
    return max(MIN_CYCLE_INTERVAL_SECONDS, min(requested, MAX_CYCLE_INTERVAL_SECONDS))


def expected_start_acknowledgment(target_evidence_type: str, revision: str) -> str:
    return f"START FULL STACK SHADOW {target_evidence_type} {revision[:12]}"


def expected_stop_acknowledgment(session_id: int) -> str:
    return f"STOP FULL STACK SHADOW {session_id}"


def _scheduler_snapshot(user: User) -> dict[str, Any]:
    return dict(scheduler_settings(user) or {})


def full_stack_shadow_preflight(
    db: Session,
    user: User,
    *,
    target_evidence_type: str = "shadow_run_4h",
) -> dict[str, Any]:
    """Return exact run prerequisites without changing any runtime setting."""

    settings = get_settings()
    operations = operations_readiness_manifest()
    scheduler = _scheduler_snapshot(user)
    revision = current_revision()
    target_supported = target_evidence_type in TARGET_SECONDS
    checks = {
        "target_supported": target_supported,
        "candidate_revision_known": revision != "unknown",
        "real_submission_disabled": settings.allow_real_application_submit is False,
        "global_autopilot_enabled": bool(operations.get("autopilot_enabled")),
        "global_kill_switch_clear": not bool(operations.get("global_kill_switch")),
        "scheduler_auto_search_enabled": bool(scheduler.get("auto_search_enabled")),
        "scheduler_auto_apply_enabled": bool(scheduler.get("auto_apply_enabled")),
        "scheduler_dry_run_enabled": bool(scheduler.get("dry_run_mode", True)),
    }
    blockers = [name for name, passed in checks.items() if not passed]
    requested_duration = TARGET_SECONDS.get(target_evidence_type)
    return {
        "ok": not blockers,
        "checks": checks,
        "blockers": blockers,
        "candidate_revision": revision,
        "target_evidence_type": target_evidence_type,
        "requested_duration_seconds": requested_duration,
        "expected_start_acknowledgment": (
            expected_start_acknowledgment(target_evidence_type, revision)
            if target_supported and revision != "unknown"
            else None
        ),
        "scheduler": scheduler,
        "operations": {
            "autopilot_enabled": bool(operations.get("autopilot_enabled")),
            "global_kill_switch": bool(operations.get("global_kill_switch")),
            "disabled_platforms": list(operations.get("disabled_platforms") or []),
        },
        "runtime": {
            "allow_real_application_submit": bool(settings.allow_real_application_submit),
            "allow_real_followup_send": bool(settings.allow_real_followup_send),
        },
        "invariants": {
            "final_submit_allowed": False,
            "runtime_settings_mutated": False,
            "outreach_authorized": False,
            "adapter_maturity_mutated": False,
        },
    }


def _baseline_snapshot(db: Session, user_id: int, now: datetime) -> dict[str, Any]:
    return {
        "captured_at": _iso(now),
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
    user_id: int,
    target_evidence_type: str,
    acknowledgment: str,
    cycle_interval_seconds: int | None = None,
    now: datetime | None = None,
) -> ShadowRunSession:
    """Create one account-scoped campaign after exact acknowledgment and preflight."""

    current = ensure_aware(now) or utc_now()
    user = (
        db.query(User)
        .filter(User.id == user_id, User.is_active == True)
        .with_for_update()
        .first()
    )
    if user is None:
        raise ShadowCampaignError("Active user not found")

    preflight = full_stack_shadow_preflight(
        db,
        user,
        target_evidence_type=target_evidence_type,
    )
    if not preflight["ok"]:
        raise ShadowCampaignError(
            "Shadow campaign preflight blocked: " + ", ".join(preflight["blockers"])
        )
    expected = str(preflight["expected_start_acknowledgment"])
    if acknowledgment.strip() != expected:
        raise ShadowCampaignError(f"Exact shadow acknowledgment required: {expected}")

    active = (
        db.query(ShadowRunSession)
        .filter(
            ShadowRunSession.user_id == user_id,
            ShadowRunSession.status.in_(ACTIVE_SESSION_STATES),
        )
        .order_by(ShadowRunSession.id.desc())
        .first()
    )
    if active is not None:
        raise ShadowCampaignError(f"Active shadow campaign already exists: {active.id}")

    duration = int(TARGET_SECONDS[target_evidence_type])
    interval = _bounded_interval(cycle_interval_seconds)
    revision = str(preflight["candidate_revision"])
    configuration = {
        "version": SHADOW_CAMPAIGN_VERSION,
        "candidate_revision": revision,
        "target_evidence_type": target_evidence_type,
        "scheduler": dict(preflight["scheduler"]),
        "operations": dict(preflight["operations"]),
        "runtime": dict(preflight["runtime"]),
        "invariants": {
            "actual_scheduler_cycle_required": True,
            "dry_run_required": True,
            "real_submission_must_remain_disabled": True,
            "final_submit_allowed": False,
            "runtime_settings_are_not_mutated_by_shadow_supervisor": True,
            "submission_authorized": False,
            "outreach_authorized": False,
        },
    }
    session = ShadowRunSession(
        user_id=user_id,
        candidate_revision=revision,
        target_evidence_type=target_evidence_type,
        requested_duration_seconds=duration,
        cycle_interval_seconds=interval,
        status="scheduled",
        started_at=current,
        expected_end_at=current + timedelta(seconds=duration),
        settle_deadline_at=current + timedelta(seconds=duration + SETTLE_WINDOW_SECONDS),
        last_heartbeat_at=current,
        final_submit_allowed=False,
        stop_requested=False,
        configuration_snapshot=configuration,
        baseline_snapshot=_baseline_snapshot(db, user_id, current),
    )
    db.add(session)
    db.flush()
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
            "activity": {},
            "incidents": [],
        }


def _cycle_application_ids(cycles: list[ShadowRunCycle]) -> list[int]:
    ids: list[int] = []
    for cycle in cycles:
        result = dict(cycle.scheduler_result or {})
        for raw in result.get("application_ids_queued") or []:
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue
    return ids


def _correlated_discovery_runs(
    db: Session,
    *,
    session: ShadowRunSession,
    end: datetime,
) -> list[AgentRun]:
    started = ensure_aware(session.started_at) or utc_now()
    rows = (
        db.query(AgentRun)
        .filter(
            AgentRun.user_id == session.user_id,
            AgentRun.created_at >= started,
            AgentRun.created_at <= end,
        )
        .order_by(AgentRun.created_at.asc(), AgentRun.id.asc())
        .all()
    )
    return [
        row
        for row in rows
        if int((row.result or {}).get("shadow_session_id") or 0) == int(session.id)
    ]


def _reconcile_session(
    db: Session,
    session: ShadowRunSession,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = ensure_aware(now) or utc_now()
    cycles = (
        db.query(ShadowRunCycle)
        .filter(ShadowRunCycle.session_id == session.id)
        .order_by(ShadowRunCycle.cycle_number.asc(), ShadowRunCycle.id.asc())
        .all()
    )
    referenced_ids = _cycle_application_ids(cycles)
    unique_ids = sorted(set(referenced_ids))
    duplicate_references = len(referenced_ids) - len(unique_ids)
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

    reviews = []
    if unique_ids:
        reviews = (
            db.query(ManualReviewTask)
            .filter(ManualReviewTask.application_id.in_(unique_ids))
            .all()
        )
    review_ids = {int(review.application_id) for review in reviews}

    submitted_ids: list[int] = []
    ready_ids: list[int] = []
    human_ids: list[int] = []
    failed_ids: list[int] = []
    active_ids: list[int] = []
    runaway_ids: list[int] = []
    unexplained_failure_ids: list[int] = []
    app_rows: list[dict[str, Any]] = []
    consequential_statuses = {
        ApplicationStatus.applied.value,
        ApplicationStatus.interviewing.value,
        ApplicationStatus.offer.value,
        ApplicationStatus.rejected.value,
    }
    for application_id in unique_ids:
        app = found.get(application_id)
        if app is None:
            continue
        status_value = app.status.value if hasattr(app.status, "value") else str(app.status)
        automation_state = str(app.automation_state or "")
        if status_value in consequential_statuses or automation_state in {
            ApplicationAutomationState.submitted.value,
            ApplicationAutomationState.confirmed.value,
        }:
            submitted_ids.append(application_id)
        if automation_state == ApplicationAutomationState.ready_to_apply.value:
            ready_ids.append(application_id)
        if automation_state in {
            ApplicationAutomationState.needs_review.value,
            ApplicationAutomationState.submission_uncertain.value,
        }:
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
        if automation_state in {
            ApplicationAutomationState.failed.value,
            ApplicationAutomationState.submission_uncertain.value,
        } and application_id not in review_ids:
            unexplained_failure_ids.append(application_id)
        app_rows.append(
            {
                "application_id": application_id,
                "status": status_value,
                "automation_state": automation_state,
                "submission_attempt_count": int(app.submission_attempt_count or 0),
                "target_status": str(app.application_target_status or ""),
                "has_manual_review": application_id in review_ids,
                "updated_at": _iso(app.updated_at or app.created_at),
            }
        )

    events = []
    if unique_ids:
        events = (
            db.query(ApplicationEvent)
            .filter(ApplicationEvent.application_id.in_(unique_ids))
            .order_by(ApplicationEvent.created_at.asc(), ApplicationEvent.id.asc())
            .all()
        )
    event_counts: dict[str, int] = {}
    for event in events:
        event_counts[event.event_type] = event_counts.get(event.event_type, 0) + 1

    discovery_runs = _correlated_discovery_runs(db, session=session, end=current)
    discovered_saved = sum(int((run.result or {}).get("saved") or 0) for run in discovery_runs)
    discovered_total = sum(int((run.result or {}).get("total_found") or 0) for run in discovery_runs)
    policy_escapes: list[dict[str, Any]] = []
    if submitted_ids:
        policy_escapes.append(
            {"code": "shadow_submission_occurred", "application_ids": submitted_ids}
        )
    if bool(session.final_submit_allowed):
        policy_escapes.append({"code": "shadow_final_submit_flag_changed"})

    return {
        "version": SHADOW_CAMPAIGN_VERSION,
        "session_id": session.id,
        "candidate_revision": session.candidate_revision,
        "target_evidence_type": session.target_evidence_type,
        "cycle_count": len(cycles),
        "cycle_failures": sum(1 for cycle in cycles if cycle.status == "failed"),
        "scheduler_application_references": len(referenced_ids),
        "unique_application_ids": unique_ids,
        "duplicate_application_references": duplicate_references,
        "missing_application_ids": missing_ids,
        "applications": app_rows,
        "applications_ready_to_apply": ready_ids,
        "human_boundary_application_ids": human_ids,
        "failed_application_ids": failed_ids,
        "active_application_ids": active_ids,
        "runaway_retry_application_ids": runaway_ids,
        "unexplained_failure_application_ids": unexplained_failure_ids,
        "submitted_application_ids": submitted_ids,
        "manual_review_count": len(reviews),
        "discovery": {
            "agent_runs": len(discovery_runs),
            "total_found": discovered_total,
            "saved": discovered_saved,
        },
        "application_events": event_counts,
        "unexplained_records": len(missing_ids) + len(unexplained_failure_ids),
        "policy_escapes": policy_escapes,
        "reconciled": (
            not missing_ids
            and not unexplained_failure_ids
            and not policy_escapes
            and duplicate_references == 0
        ),
    }


def _build_final_report(
    db: Session,
    session: ShadowRunSession,
    *,
    terminal_status: str,
    failure_reason: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = ensure_aware(now) or ensure_aware(session.completed_at) or utc_now()
    started = ensure_aware(session.started_at) or current
    measured = max(0.0, (current - started).total_seconds())
    reconciliation = _reconcile_session(db, session, now=current)
    observability = _observability_report(
        db,
        session.user_id,
        window_hours=max(1, int(measured // 3600) + 1),
    )
    quality = {
        "duration_satisfied": measured >= int(session.requested_duration_seconds),
        "scheduler_cycles_completed": int(session.cycles_completed or 0) > 0,
        "no_cycle_failures": int(session.cycles_failed or 0) == 0,
        "discovery_path_observed": int(reconciliation["discovery"]["agent_runs"]) > 0,
        "application_path_observed": len(reconciliation["unique_application_ids"]) > 0,
        "no_leaked_or_missing_application_records": not bool(
            reconciliation["missing_application_ids"]
        ),
        "no_duplicate_scheduler_application_references": (
            int(reconciliation["duplicate_application_references"]) == 0
        ),
        "no_false_submitted_status": not bool(reconciliation["submitted_application_ids"]),
        "no_runaway_retry": not bool(reconciliation["runaway_retry_application_ids"]),
        "no_unexplained_failures": not bool(
            reconciliation["unexplained_failure_application_ids"]
        ),
        "no_policy_escape": not bool(reconciliation["policy_escapes"]),
        "no_active_application_work": not bool(reconciliation["active_application_ids"]),
    }
    report: dict[str, Any] = {
        "version": SHADOW_CAMPAIGN_VERSION,
        "session_id": session.id,
        "status": terminal_status,
        "candidate_revision": session.candidate_revision,
        "target_evidence_type": session.target_evidence_type,
        "requested_duration_seconds": int(session.requested_duration_seconds),
        "measured_duration_seconds": measured,
        "measured_elapsed_time": True,
        "started_at": _iso(session.started_at),
        "completed_at": _iso(current),
        "cycles_completed": int(session.cycles_completed or 0),
        "cycles_failed": int(session.cycles_failed or 0),
        "configuration_snapshot": dict(session.configuration_snapshot or {}),
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
            "real_submission_remained_disabled": get_settings().allow_real_application_submit
            is False,
            "dry_run_required": True,
            "runtime_settings_changed_by_supervisor": False,
            "submission_authorized": False,
            "outreach_authorized": False,
        },
        "quality": quality,
        "failure_reason": failure_reason,
    }
    report["qualification_eligible"] = (
        terminal_status == "completed"
        and all(quality.values())
        and report["safety"]["final_submit_clicked"] is False
        and report["safety"]["real_submission_remained_disabled"] is True
    )
    report["report_sha256"] = canonical_hash(report)
    return report


def finalize_shadow_session(
    db: Session,
    session: ShadowRunSession,
    *,
    requested_status: str = "completed",
    failure_reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = ensure_aware(now) or utc_now()
    session.completed_at = current
    session.last_heartbeat_at = current
    report = _build_final_report(
        db,
        session,
        terminal_status=requested_status,
        failure_reason=failure_reason,
        now=current,
    )
    effective_status = requested_status
    effective_reason = failure_reason
    if requested_status == "completed" and not report.get("qualification_eligible"):
        effective_status = "failed"
        effective_reason = failure_reason or "shadow_reconciliation_quality_gate_failed"
        report = _build_final_report(
            db,
            session,
            terminal_status=effective_status,
            failure_reason=effective_reason,
            now=current,
        )
    session.status = effective_status
    session.failure_reason = effective_reason
    reconciliation = dict(report.get("reconciliation") or {})
    session.applications_created = len(reconciliation.get("unique_application_ids") or [])
    session.applications_ready_to_submit = len(
        reconciliation.get("applications_ready_to_apply") or []
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
    db.flush()
    return report


def _latest_running_cycle(db: Session, session_id: int) -> ShadowRunCycle | None:
    return (
        db.query(ShadowRunCycle)
        .filter(ShadowRunCycle.session_id == session_id, ShadowRunCycle.status == "running")
        .order_by(ShadowRunCycle.cycle_number.desc(), ShadowRunCycle.id.desc())
        .first()
    )


def execute_shadow_cycle(
    db: Session,
    *,
    session_id: int,
    scheduler_runner: Callable[..., dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute one production scheduler cycle or settle a completed-duration session."""

    current = ensure_aware(now) or utc_now()
    session = (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.id == session_id)
        .with_for_update()
        .first()
    )
    if session is None:
        return {"status": "missing", "session_id": session_id, "schedule_next": False}
    if session.status in TERMINAL_SESSION_STATES:
        return {"status": session.status, "session_id": session.id, "schedule_next": False}

    if session.stop_requested or session.status == "stopping":
        report = finalize_shadow_session(
            db,
            session,
            requested_status="cancelled",
            failure_reason="operator_stop_requested",
            now=current,
        )
        return {
            "status": "cancelled",
            "session_id": session.id,
            "schedule_next": False,
            "report": report,
        }

    user = db.query(User).filter(User.id == session.user_id, User.is_active == True).first()
    if user is None:
        report = finalize_shadow_session(
            db,
            session,
            requested_status="failed",
            failure_reason="shadow_user_missing",
            now=current,
        )
        return {"status": "failed", "session_id": session.id, "schedule_next": False, "report": report}

    preflight = full_stack_shadow_preflight(
        db,
        user,
        target_evidence_type=session.target_evidence_type,
    )
    blockers = list(preflight.get("blockers") or [])
    if str(preflight.get("candidate_revision")) != str(session.candidate_revision):
        blockers.append("candidate_revision_changed")
    if blockers:
        report = finalize_shadow_session(
            db,
            session,
            requested_status="failed",
            failure_reason="shadow_preflight_changed:" + ",".join(sorted(set(blockers))),
            now=current,
        )
        return {"status": "failed", "session_id": session.id, "schedule_next": False, "report": report}

    expected_end = ensure_aware(session.expected_end_at) or current
    settle_deadline = ensure_aware(session.settle_deadline_at) or (
        expected_end + timedelta(seconds=SETTLE_WINDOW_SECONDS)
    )
    if session.status == "settling" or current >= expected_end:
        reconciliation = _reconcile_session(db, session, now=current)
        active_ids = list(reconciliation.get("active_application_ids") or [])
        if active_ids and current < settle_deadline:
            session.status = "settling"
            session.last_heartbeat_at = current
            db.flush()
            return {
                "status": "settling",
                "session_id": session.id,
                "schedule_next": True,
                "countdown_seconds": min(300, int(session.cycle_interval_seconds)),
                "active_application_ids": active_ids,
                "settle_deadline_at": _iso(settle_deadline),
            }
        report = finalize_shadow_session(
            db,
            session,
            requested_status="completed",
            now=current,
        )
        return {
            "status": session.status,
            "session_id": session.id,
            "schedule_next": False,
            "report": report,
        }

    running_cycle = _latest_running_cycle(db, session.id)
    if running_cycle is not None:
        started = ensure_aware(running_cycle.started_at) or current
        timeout_seconds = max(1800, int(session.cycle_interval_seconds) * 2)
        if (current - started).total_seconds() < timeout_seconds:
            return {
                "status": "cycle_in_progress",
                "session_id": session.id,
                "cycle_id": running_cycle.id,
                "schedule_next": False,
            }
        running_cycle.status = "failed"
        running_cycle.completed_at = current
        running_cycle.error_detail = "stale_shadow_cycle_recovered"
        session.cycles_failed = int(session.cycles_failed or 0) + 1

    if scheduler_runner is None:
        from app.tasks.scraping import _run_scheduler_cycle_for_user

        scheduler_runner = _run_scheduler_cycle_for_user

    cycle_number = int(session.cycles_completed or 0) + int(session.cycles_failed or 0) + 1
    cycle = ShadowRunCycle(
        session_id=session.id,
        cycle_number=cycle_number,
        status="running",
        started_at=current,
    )
    db.add(cycle)
    session.status = "running"
    session.last_heartbeat_at = current
    db.flush()

    try:
        result = scheduler_runner(db, user, shadow_session_id=session.id)
        if not isinstance(result, dict):
            result = {"raw_result": str(result)}
        if result.get("real_submission_enabled") is not False:
            raise RuntimeError("shadow_scheduler_reported_real_submission_enabled")
        if result.get("dry_run") is not True:
            raise RuntimeError("shadow_scheduler_reported_dry_run_false")
        if int(result.get("shadow_session_id") or 0) != int(session.id):
            raise RuntimeError("shadow_scheduler_correlation_missing")

        cycle.scheduler_result = result
        cycle.observability_snapshot = _observability_report(
            db,
            session.user_id,
            window_hours=max(1, int(session.requested_duration_seconds // 3600) + 1),
        )
        cycle.reconciliation_snapshot = {
            "applications_queued": int(result.get("applications_queued") or 0),
            "application_ids_queued": list(result.get("application_ids_queued") or []),
            "searched": bool(result.get("searched")),
            "search_task_id": result.get("search_task_id"),
            "reason": result.get("reason"),
            "dry_run": bool(result.get("dry_run")),
            "real_submission_enabled": bool(result.get("real_submission_enabled")),
        }
        cycle.status = "completed"
        cycle.completed_at = current
        session.cycles_completed = int(session.cycles_completed or 0) + 1
        session.last_cycle_at = current
        session.last_heartbeat_at = current
        db.flush()
    except Exception as exc:
        cycle.status = "failed"
        cycle.completed_at = current
        cycle.error_detail = str(exc)[:1800]
        session.cycles_failed = int(session.cycles_failed or 0) + 1
        session.last_cycle_at = current
        session.last_heartbeat_at = current
        db.flush()
        recent = (
            db.query(ShadowRunCycle)
            .filter(ShadowRunCycle.session_id == session.id)
            .order_by(ShadowRunCycle.cycle_number.desc(), ShadowRunCycle.id.desc())
            .limit(3)
            .all()
        )
        if len(recent) >= 3 and all(item.status == "failed" for item in recent):
            report = finalize_shadow_session(
                db,
                session,
                requested_status="failed",
                failure_reason="three_consecutive_shadow_cycle_failures",
                now=current,
            )
            return {
                "status": "failed",
                "session_id": session.id,
                "schedule_next": False,
                "report": report,
            }

    return {
        "status": "running",
        "session_id": session.id,
        "schedule_next": True,
        "countdown_seconds": int(session.cycle_interval_seconds),
        "cycles_completed": int(session.cycles_completed or 0),
        "cycles_failed": int(session.cycles_failed or 0),
        "expected_end_at": _iso(session.expected_end_at),
        "submission_authorized": False,
        "outreach_authorized": False,
    }


def request_shadow_stop(
    db: Session,
    *,
    user_id: int,
    session_id: int,
    acknowledgment: str,
) -> ShadowRunSession:
    session = (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.id == session_id, ShadowRunSession.user_id == user_id)
        .with_for_update()
        .first()
    )
    if session is None:
        raise ShadowCampaignError("Shadow campaign not found")
    if session.status in TERMINAL_SESSION_STATES:
        return session
    expected = expected_stop_acknowledgment(session.id)
    if acknowledgment.strip() != expected:
        raise ShadowCampaignError(f"Exact shadow acknowledgment required: {expected}")
    session.stop_requested = True
    session.status = "stopping"
    session.last_heartbeat_at = utc_now()
    db.flush()
    return session


def mark_shadow_dispatch_failure(
    db: Session,
    *,
    session_id: int,
    detail: str,
) -> None:
    session = db.query(ShadowRunSession).filter(ShadowRunSession.id == session_id).first()
    if session is None or session.status in TERMINAL_SESSION_STATES:
        return
    session.status = "failed"
    session.failure_reason = f"shadow_dispatch_failed:{detail[:700]}"
    session.completed_at = utc_now()
    session.last_heartbeat_at = session.completed_at
    db.flush()


def list_shadow_sessions(
    db: Session,
    *,
    user_id: int,
    limit: int = 50,
) -> list[ShadowRunSession]:
    return (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.user_id == user_id)
        .order_by(ShadowRunSession.created_at.desc(), ShadowRunSession.id.desc())
        .limit(max(1, min(int(limit), 200)))
        .all()
    )


def owned_shadow_session(
    db: Session,
    *,
    user_id: int,
    session_id: int,
) -> ShadowRunSession:
    session = (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.id == session_id, ShadowRunSession.user_id == user_id)
        .first()
    )
    if session is None:
        raise ShadowCampaignError("Shadow campaign not found")
    return session


def shadow_session_status(db: Session, *, session: ShadowRunSession) -> dict[str, Any]:
    current = ensure_aware(session.completed_at) or utc_now()
    started = ensure_aware(session.started_at) or current
    measured = max(0.0, (current - started).total_seconds())
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
        "target_evidence_type": session.target_evidence_type,
        "requested_duration_seconds": int(session.requested_duration_seconds),
        "measured_duration_seconds": measured,
        "cycle_interval_seconds": int(session.cycle_interval_seconds),
        "started_at": _iso(session.started_at),
        "expected_end_at": _iso(session.expected_end_at),
        "settle_deadline_at": _iso(session.settle_deadline_at),
        "completed_at": _iso(session.completed_at),
        "last_cycle_at": _iso(session.last_cycle_at),
        "last_heartbeat_at": _iso(session.last_heartbeat_at),
        "cycles_completed": int(session.cycles_completed or 0),
        "cycles_failed": int(session.cycles_failed or 0),
        "stop_requested": bool(session.stop_requested),
        "final_submit_allowed": bool(session.final_submit_allowed),
        "applications_created": int(session.applications_created or 0),
        "applications_ready_to_submit": int(session.applications_ready_to_submit or 0),
        "human_boundaries": int(session.human_boundaries or 0),
        "unexplained_records": int(session.unexplained_records or 0),
        "duplicate_application_ids": int(session.duplicate_application_ids or 0),
        "runaway_retry_count": int(session.runaway_retry_count or 0),
        "failure_reason": session.failure_reason,
        "configuration_snapshot": dict(session.configuration_snapshot or {}),
        "report_sha256": session.report_sha256,
        "certification_evidence_id": session.certification_evidence_id,
        "final_report": dict(session.final_report or {}),
        "expected_stop_acknowledgment": expected_stop_acknowledgment(session.id),
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
        "submission_authorized": False,
        "outreach_authorized": False,
    }


def record_shadow_certification_evidence(
    db: Session,
    *,
    user_id: int,
    session_id: int,
) -> tuple[CertificationEvidence, bool]:
    """Bridge one completed campaign to an unreviewed Phase 10 evidence record."""

    session = owned_shadow_session(db, user_id=user_id, session_id=session_id)
    if session.status != "completed":
        raise ShadowCampaignError("Only completed shadow campaigns can record evidence")
    if session.certification_evidence_id:
        existing = db.query(CertificationEvidence).filter(
            CertificationEvidence.id == session.certification_evidence_id,
            CertificationEvidence.recorded_by_user_id == user_id,
        ).first()
        if existing is not None:
            return existing, True

    if str(session.candidate_revision) != str(current_revision()):
        raise ShadowCampaignError("Shadow campaign is not bound to the current candidate revision")
    stored_report = dict(session.final_report or {})
    if not stored_report or not session.report_sha256:
        raise ShadowCampaignError("Shadow campaign has no retained final report")
    report_without_hash = dict(stored_report)
    stored_hash = str(report_without_hash.pop("report_sha256", ""))
    if not stored_hash or canonical_hash(report_without_hash) != stored_hash:
        raise ShadowCampaignError("Shadow campaign report hash mismatch")
    if stored_hash != str(session.report_sha256):
        raise ShadowCampaignError("Shadow campaign retained report identity mismatch")
    if stored_report.get("qualification_eligible") is not True:
        raise ShadowCampaignError("Shadow campaign did not satisfy qualification gates")
    if stored_report.get("target_evidence_type") != session.target_evidence_type:
        raise ShadowCampaignError("Shadow campaign target evidence drift detected")

    metadata = {
        "full_stack_shadow_session": True,
        "session_id": session.id,
        "report_sha256": stored_hash,
        "measured_elapsed_time": True,
        "final_submit_enabled": False,
        "final_submit_clicked": False,
        "real_submission_remained_disabled": True,
        "qualification_eligible": True,
        "cycles_completed": int(session.cycles_completed or 0),
        "cycles_failed": int(session.cycles_failed or 0),
        "applications_created": int(session.applications_created or 0),
        "human_boundaries": int(session.human_boundaries or 0),
        "reconciled": bool((stored_report.get("reconciliation") or {}).get("reconciled")),
        "submission_authorized": False,
        "outreach_authorized": False,
    }
    payload = evidence_payload(
        evidence_type=session.target_evidence_type,
        adapter=None,
        commit_sha=session.candidate_revision,
        environment="full-stack-shadow",
        status="passed",
        duration_seconds=int(float(stored_report.get("measured_duration_seconds") or 0)),
        source_reference=f"full-stack-shadow-session:{session.id}:{stored_hash}",
        evidence_metadata=metadata,
    )
    key = evidence_key_for(payload, owner_user_id=user_id)
    existing = db.query(CertificationEvidence).filter(CertificationEvidence.evidence_key == key).first()
    if existing is not None:
        session.certification_evidence_id = existing.id
        db.flush()
        return existing, True

    record = CertificationEvidence(
        evidence_key=key,
        evidence_type=session.target_evidence_type,
        adapter=None,
        commit_sha=session.candidate_revision,
        environment="full-stack-shadow",
        status="passed",
        duration_seconds=payload["duration_seconds"],
        source_reference=payload["source_reference"],
        payload_hash=canonical_hash(payload),
        evidence_metadata=metadata,
        recorded_by_user_id=user_id,
        review_status="unreviewed",
    )
    db.add(record)
    db.flush()
    session.certification_evidence_id = record.id
    db.flush()
    return record, False


__all__ = [
    "ACTIVE_SESSION_STATES",
    "DEFAULT_CYCLE_INTERVAL_SECONDS",
    "SETTLE_WINDOW_SECONDS",
    "SHADOW_CAMPAIGN_VERSION",
    "TARGET_SECONDS",
    "TERMINAL_SESSION_STATES",
    "ShadowCampaignError",
    "create_shadow_session",
    "execute_shadow_cycle",
    "expected_start_acknowledgment",
    "expected_stop_acknowledgment",
    "finalize_shadow_session",
    "full_stack_shadow_preflight",
    "list_shadow_sessions",
    "mark_shadow_dispatch_failure",
    "owned_shadow_session",
    "record_shadow_certification_evidence",
    "request_shadow_stop",
    "shadow_session_status",
]