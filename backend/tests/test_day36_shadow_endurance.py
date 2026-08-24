from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.application import Application, ApplicationAutomationState, ApplicationStatus
from app.models.certification import ShadowRunCycle, ShadowRunSession
from app.models.job import Job, JobSource, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services import day36_endurance_runtime, full_stack_shadow
from app.services.certification_scale import canonical_hash
from app.services.day36_shadow_endurance import (
    DAY36_SECONDS,
    build_day36_shadow_endurance_report,
)


REVISION = "6" * 40
START = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


def _user(db) -> User:
    user = User(
        email="day36@example.com",
        hashed_password="hash",
        full_name="Day 36",
        profile_data={},
        job_preferences={},
        automation_settings={},
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _application(db, user: User, *, automation_log=None) -> Application:
    job = Job(
        external_id="day36-lever-job",
        title="Risk Analyst",
        company="Endurance Labs",
        location="Remote",
        url="https://jobs.lever.co/endurance/abc",
        source=JobSource.lever,
        status=JobStatus.approved,
        relevance_score=0.94,
        raw_data={"workplace_mode": "remote"},
    )
    db.add(job)
    db.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        submission_idempotency_key="day36-application-key",
        submission_attempt_count=1,
        automation_log=list(automation_log or []),
    )
    db.add(application)
    db.flush()
    return application


def _phase11_report(application_id: int, *, completed_at: datetime, measured=None) -> dict:
    reconciliation = {
        "unique_application_ids": [application_id],
        "duplicate_application_references": 0,
        "submitted_application_ids": [],
        "runaway_retry_application_ids": [],
        "unexplained_records": 0,
        "policy_escapes": [],
        "active_application_ids": [],
        "discovery": {"agent_runs": 4, "total_found": 12, "saved": 4},
    }
    quality = {
        "duration_satisfied": True,
        "scheduler_cycles_completed": True,
        "no_cycle_failures": True,
        "discovery_path_observed": True,
        "application_path_observed": True,
        "no_leaked_or_missing_application_records": True,
        "no_duplicate_scheduler_application_references": True,
        "no_false_submitted_status": True,
        "no_runaway_retry": True,
        "no_unexplained_failures": True,
        "no_policy_escape": True,
        "no_active_application_work": True,
    }
    report = {
        "version": "phase11-full-stack-shadow-v1",
        "session_id": 0,
        "status": "completed",
        "candidate_revision": REVISION,
        "target_evidence_type": "shadow_run_4h",
        "requested_duration_seconds": DAY36_SECONDS,
        "measured_duration_seconds": float(measured if measured is not None else (completed_at - START).total_seconds()),
        "measured_elapsed_time": True,
        "started_at": START.replace(microsecond=0).isoformat(),
        "completed_at": completed_at.replace(microsecond=0).isoformat(),
        "cycles_completed": 16,
        "cycles_failed": 0,
        "reconciliation": reconciliation,
        "observability": {"summary": {}, "activity": {}, "incidents": [], "unavailable": False},
        "safety": {
            "final_submit_enabled": False,
            "final_submit_clicked": False,
            "real_submission_remained_disabled": True,
            "dry_run_required": True,
            "runtime_settings_changed_by_supervisor": False,
            "submission_authorized": False,
            "outreach_authorized": False,
        },
        "quality": quality,
        "failure_reason": None,
        "qualification_eligible": True,
    }
    return report


def _session(
    db,
    user: User,
    application: Application,
    *,
    completed_at: datetime | None = None,
    include_memory: bool = True,
    measured: float | None = None,
) -> ShadowRunSession:
    finish = completed_at or (START + timedelta(hours=4, minutes=1))
    session = ShadowRunSession(
        user_id=user.id,
        candidate_revision=REVISION,
        target_evidence_type="shadow_run_4h",
        requested_duration_seconds=DAY36_SECONDS,
        cycle_interval_seconds=15 * 60,
        status="completed",
        started_at=START,
        expected_end_at=START + timedelta(hours=4),
        settle_deadline_at=START + timedelta(hours=4, minutes=45),
        completed_at=finish,
        last_cycle_at=START + timedelta(hours=3, minutes=46),
        last_heartbeat_at=finish,
        cycles_completed=16,
        cycles_failed=0,
        final_submit_allowed=False,
        stop_requested=False,
        configuration_snapshot={"invariants": {"final_submit_allowed": False}},
        baseline_snapshot={},
    )
    db.add(session)
    db.flush()

    for index in range(16):
        started = START + timedelta(minutes=1 + index * 15)
        memory = (
            {
                "day36_runtime_memory": {
                    "version": "day36-shadow-endurance-v1",
                    "source": "proc_status",
                    "rss_kib": 120_000 + index * 500,
                    "peak_rss_kib": 130_000 + index * 500,
                    "pid": 4242,
                }
            }
            if include_memory
            else {}
        )
        db.add(
            ShadowRunCycle(
                session_id=session.id,
                cycle_number=index + 1,
                status="completed",
                started_at=started,
                completed_at=started + timedelta(minutes=1),
                scheduler_result={
                    "shadow_session_id": session.id,
                    "dry_run": True,
                    "real_submission_enabled": False,
                    "applications_queued": 1 if index == 0 else 0,
                    "application_ids_queued": [application.id] if index == 0 else [],
                },
                observability_snapshot=memory,
                reconciliation_snapshot={"applications_queued": 1 if index == 0 else 0},
            )
        )

    report = _phase11_report(application.id, completed_at=finish, measured=measured)
    report["session_id"] = session.id
    report["report_sha256"] = canonical_hash(report)
    # The Phase 11 hash is computed before the hash field is present.
    payload = dict(report)
    payload.pop("report_sha256")
    report["report_sha256"] = canonical_hash(payload)
    session.final_report = report
    session.report_sha256 = report["report_sha256"]
    db.flush()
    return session


def test_real_shaped_four_hour_endurance_evidence_passes(db_session):
    user = _user(db_session)
    application = _application(db_session, user)
    session = _session(db_session, user, application)

    report = build_day36_shadow_endurance_report(
        db_session,
        session_id=session.id,
        user_id=user.id,
        expected_revision=REVISION,
    )

    assert report["passed"] is True
    assert report["day37_entry_eligible"] is True
    assert report["persisted_elapsed_seconds"] >= DAY36_SECONDS
    assert report["cycle_coverage"]["continuous_cycle_coverage"] is True
    assert report["memory"]["sample_count"] == 16
    assert report["throughput"]["cycle_error_rate"] == 0
    assert report["browser_cleanup"]["cleanup_reconciled"] is True
    assert report["notification_quality"]["quality_ok"] is True
    assert report["safety"]["submission_authorized"] is False
    assert report["safety"]["promotion_authorized"] is False


def test_forged_four_hour_report_cannot_hide_short_persisted_runtime(db_session):
    user = _user(db_session)
    application = _application(db_session, user)
    finish = START + timedelta(hours=3, minutes=59)
    session = _session(
        db_session,
        user,
        application,
        completed_at=finish,
        measured=DAY36_SECONDS + 60,
    )

    report = build_day36_shadow_endurance_report(
        db_session,
        session_id=session.id,
        expected_revision=REVISION,
    )

    assert report["passed"] is False
    assert report["checks"]["persisted_elapsed_at_least_4h"] is False


def test_memory_telemetry_is_required_for_day36(db_session):
    user = _user(db_session)
    application = _application(db_session, user)
    session = _session(db_session, user, application, include_memory=False)

    report = build_day36_shadow_endurance_report(
        db_session,
        session_id=session.id,
        expected_revision=REVISION,
    )

    assert report["passed"] is False
    assert report["checks"]["memory_telemetry_present"] is False


def test_candidate_revision_drift_blocks_endurance_evidence(db_session):
    user = _user(db_session)
    application = _application(db_session, user)
    session = _session(db_session, user, application)

    report = build_day36_shadow_endurance_report(
        db_session,
        session_id=session.id,
        expected_revision="7" * 40,
    )

    assert report["passed"] is False
    assert report["checks"]["candidate_revision_matches_exact_runtime"] is False


def test_unaccounted_retained_browser_session_fails_cleanup_gate(db_session):
    user = _user(db_session)
    application = _application(
        db_session,
        user,
        automation_log=[{"action": "browser_handoff_retained", "browser_session_id": "orphan"}],
    )
    session = _session(db_session, user, application)

    report = build_day36_shadow_endurance_report(
        db_session,
        session_id=session.id,
        expected_revision=REVISION,
    )

    assert report["passed"] is False
    assert report["checks"]["browser_cleanup_reconciled"] is False
    assert report["browser_cleanup"]["unaccounted_retained_browser_application_ids"] == [application.id]


def test_duplicate_campaign_notifications_fail_quality_gate(db_session):
    user = _user(db_session)
    application = _application(db_session, user)
    session = _session(db_session, user, application)
    for _ in range(2):
        db_session.add(
            Notification(
                user_id=user.id,
                type=NotificationType.system,
                title="Manual review needed",
                message="Review this application",
                data={"application_id": application.id, "reason": "captcha_detected"},
                created_at=START + timedelta(hours=1),
            )
        )
    db_session.flush()

    report = build_day36_shadow_endurance_report(
        db_session,
        session_id=session.id,
        expected_revision=REVISION,
    )

    assert report["passed"] is False
    assert report["checks"]["notification_quality_ok"] is False
    assert report["notification_quality"]["duplicate_notification_groups"] == 1


def test_endurance_runtime_wrapper_adds_memory_without_changing_authority(monkeypatch):
    monkeypatch.setattr(day36_endurance_runtime, "_INSTALLED", False)
    monkeypatch.setattr(
        day36_endurance_runtime,
        "process_memory_snapshot",
        lambda: {"rss_kib": 123, "peak_rss_kib": 456, "pid": 1, "source": "test"},
    )
    monkeypatch.setattr(
        full_stack_shadow,
        "_observability_report",
        lambda db, user_id, window_hours: {
            "summary": {"incident_count": 0},
            "activity": {},
            "incidents": [],
        },
    )

    day36_endurance_runtime.install_day36_endurance_runtime()
    report = full_stack_shadow._observability_report(None, 1, window_hours=5)

    assert report["day36_runtime_memory"]["rss_kib"] == 123
    assert report["summary"]["incident_count"] == 0
    assert "submission_authorized" not in report
