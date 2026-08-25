from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.application import Application, ApplicationAutomationState, ApplicationStatus
from app.models.certification import CertificationEvidence, ShadowRunCycle, ShadowRunSession
from app.models.job import Job, JobSource, JobStatus
from app.services import full_stack_shadow
from app.services.certification_scale import canonical_hash
from app.services.day37_shadow_endurance import (
    DAY37_SECONDS,
    build_day37_shadow_endurance_report,
)
from app.services.day37_shadow_incidents import DAY37_INCIDENT_PLAN, DAY37_INCIDENT_VERSION
from app.services.full_stack_shadow import record_shadow_certification_evidence
from tests.test_day36_shadow_endurance import (
    REVISION as DAY36_REVISION,
    _application as _day36_application,
    _session as _day36_session,
    _user as _day36_user,
)


DAY37_REVISION = "7" * 40
START = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _rehash_session_report(session: ShadowRunSession, report: dict) -> None:
    payload = dict(report)
    payload.pop("report_sha256", None)
    report["report_sha256"] = canonical_hash(payload)
    session.final_report = report
    session.report_sha256 = report["report_sha256"]


def _seed_verified_day36_predecessor(db_session, monkeypatch):
    user = _day36_user(db_session)
    application = _day36_application(db_session, user)
    session = _day36_session(db_session, user, application)

    report = dict(session.final_report or {})
    reconciliation = dict(report.get("reconciliation") or {})
    reconciliation["reconciled"] = True
    report["reconciliation"] = reconciliation
    _rehash_session_report(session, report)
    db_session.flush()

    monkeypatch.setattr(full_stack_shadow, "current_revision", lambda: DAY36_REVISION)
    evidence, duplicate = record_shadow_certification_evidence(
        db_session,
        user_id=user.id,
        session_id=session.id,
    )
    assert duplicate is False
    evidence.review_status = "verified"
    evidence.reviewed_by_user_id = user.id
    evidence.reviewed_at = START - timedelta(hours=1)
    evidence.review_reference = "review:day36-physical-endurance"
    db_session.flush()

    return user, session, evidence


def _day37_application(db_session, user) -> Application:
    job = Job(
        external_id="day37-lever-job",
        title="Operational Risk Analyst",
        company="Eight Hour Labs",
        location="Remote",
        url="https://jobs.lever.co/eight-hour-labs/day37",
        source=JobSource.lever,
        status=JobStatus.approved,
        relevance_score=0.95,
        raw_data={"workplace_mode": "remote"},
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        submission_idempotency_key="day37-eight-hour-application",
        submission_attempt_count=1,
        automation_log=[],
    )
    db_session.add(application)
    db_session.flush()
    return application


def _incident_payload(incident_type: str, *, passed: bool = True) -> dict:
    planned = next(item for item in DAY37_INCIDENT_PLAN if item["incident_type"] == incident_type)
    observed_by_type = {
        "source_outage": {
            "failed_source_count": 1,
            "successful_source_count": 1,
            "surviving_result_count": 1,
            "failed_error_code": "day37injectedsourceoutage",
            "raw_exception_retained": False,
        },
        "browser_crash": {
            "controlled_page_destroyed": True,
            "fresh_controlled_page_recovered": True,
            "first_target_present": True,
            "second_target_present": True,
            "fresh_target_identity": True,
            "browser_process_kill_requested": False,
        },
        "stale_posting": {
            "reason_code": "listing_closed",
            "terminal": True,
            "retryable": False,
            "matched_text_present": True,
        },
        "ambiguous_question": {
            "canonical_key": "custom.unclassified",
            "matched": False,
            "can_autofill": False,
            "answer_generated": False,
            "review_reason": "ambiguous_question",
        },
    }
    elapsed = int(planned["minimum_elapsed_seconds"]) + 60
    return {
        "version": DAY37_INCIDENT_VERSION,
        "incident_type": incident_type,
        "planned_minimum_elapsed_seconds": int(planned["minimum_elapsed_seconds"]),
        "observed_elapsed_seconds": float(elapsed),
        "injected_at": (START + timedelta(seconds=elapsed)).isoformat(),
        "status": "passed" if passed else "failed",
        "recovery_contract": planned["recovery_contract"],
        "observed": observed_by_type[incident_type],
        "error_code": None if passed else "controlled_fixture_failure",
        "breaker_state": {
            "allowed": True,
            "code": "circuit_breaker_closed",
            "reason": "No active clustered-failure circuit breaker applies.",
            "metadata": {"platform": None},
        },
        "safety": {
            "real_submission_requested": False,
            "outreach_requested": False,
            "adapter_maturity_mutated": False,
            "browser_process_kill_requested": False,
        },
    }


def _day37_report(session: ShadowRunSession, application: Application, *, finish: datetime) -> dict:
    reconciliation = {
        "reconciled": True,
        "unique_application_ids": [application.id],
        "missing_application_ids": [],
        "duplicate_application_references": 0,
        "applications_ready_to_apply": [application.id],
        "human_boundary_application_ids": [],
        "failed_application_ids": [],
        "active_application_ids": [],
        "runaway_retry_application_ids": [],
        "unexplained_failure_application_ids": [],
        "submitted_application_ids": [],
        "manual_review_count": 0,
        "discovery": {"agent_runs": 8, "total_found": 24, "saved": 8},
        "application_events": {},
        "unexplained_records": 0,
        "policy_escapes": [],
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
    return {
        "version": "phase11-full-stack-shadow-v1",
        "session_id": session.id,
        "status": "completed",
        "candidate_revision": DAY37_REVISION,
        "target_evidence_type": "shadow_run_8h",
        "requested_duration_seconds": DAY37_SECONDS,
        "measured_duration_seconds": float((finish - START).total_seconds()),
        "measured_elapsed_time": True,
        "started_at": START.isoformat(),
        "completed_at": finish.isoformat(),
        "cycles_completed": 32,
        "cycles_failed": 0,
        "configuration_snapshot": dict(session.configuration_snapshot or {}),
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


def _day37_session(
    db_session,
    user,
    application: Application,
    *,
    failed_incident: str | None = None,
    drift_worker_pid: bool = False,
    finish: datetime | None = None,
) -> ShadowRunSession:
    completed = finish or (START + timedelta(hours=8, minutes=1))
    session = ShadowRunSession(
        user_id=user.id,
        candidate_revision=DAY37_REVISION,
        target_evidence_type="shadow_run_8h",
        requested_duration_seconds=DAY37_SECONDS,
        cycle_interval_seconds=15 * 60,
        status="completed",
        started_at=START,
        expected_end_at=START + timedelta(hours=8),
        settle_deadline_at=START + timedelta(hours=8, minutes=45),
        completed_at=completed,
        last_cycle_at=START + timedelta(hours=7, minutes=46),
        last_heartbeat_at=completed,
        cycles_completed=32,
        cycles_failed=0,
        applications_created=1,
        applications_ready_to_submit=1,
        human_boundaries=0,
        unexplained_records=0,
        duplicate_application_ids=0,
        runaway_retry_count=0,
        final_submit_allowed=False,
        stop_requested=False,
        configuration_snapshot={
            "invariants": {
                "dry_run_required": True,
                "real_submission_must_remain_disabled": True,
                "final_submit_allowed": False,
            }
        },
        baseline_snapshot={},
    )
    db_session.add(session)
    db_session.flush()

    incident_cycle = {
        "source_outage": 5,
        "browser_crash": 13,
        "stale_posting": 21,
        "ambiguous_question": 27,
    }
    for index in range(32):
        cycle_number = index + 1
        started = START + timedelta(minutes=1 + index * 15)
        pid = 4243 if drift_worker_pid and cycle_number == 32 else 4242
        observability = {
            "day36_runtime_memory": {
                "version": "day36-shadow-endurance-v1",
                "source": "proc_status",
                "rss_kib": 120_000 + index * 250,
                "peak_rss_kib": 130_000 + index * 250,
                "pid": pid,
            }
        }
        for incident_type, target_cycle in incident_cycle.items():
            if cycle_number == target_cycle:
                observability["day37_incident"] = _incident_payload(
                    incident_type,
                    passed=incident_type != failed_incident,
                )
        db_session.add(
            ShadowRunCycle(
                session_id=session.id,
                cycle_number=cycle_number,
                status="completed",
                started_at=started,
                completed_at=started + timedelta(minutes=1),
                scheduler_result={
                    "shadow_session_id": session.id,
                    "dry_run": True,
                    "real_submission_enabled": False,
                    "applications_queued": 1 if cycle_number == 1 else 0,
                    "application_ids_queued": [application.id] if cycle_number == 1 else [],
                },
                observability_snapshot=observability,
                reconciliation_snapshot={"applications_queued": 1 if cycle_number == 1 else 0},
            )
        )

    report = _day37_report(session, application, finish=completed)
    _rehash_session_report(session, report)
    db_session.flush()
    return session


def test_real_shaped_eight_hour_endurance_evidence_passes(
    db_session,
    monkeypatch,
):
    user, predecessor_session, predecessor_evidence = _seed_verified_day36_predecessor(
        db_session,
        monkeypatch,
    )
    application = _day37_application(db_session, user)
    session = _day37_session(db_session, user, application)

    report = build_day37_shadow_endurance_report(
        db_session,
        session_id=session.id,
        user_id=user.id,
        expected_revision=DAY37_REVISION,
    )

    assert predecessor_session.id != session.id
    assert predecessor_evidence.review_status == "verified"
    assert report["passed"] is True
    assert report["day38_entry_eligible"] is True
    assert report["persisted_elapsed_seconds"] >= DAY37_SECONDS
    assert report["cycle_coverage"]["continuous_cycle_coverage"] is True
    assert report["memory"]["distinct_worker_pids"] == [4242]
    assert report["incidents"]["observed_types"] == [
        "source_outage",
        "browser_crash",
        "stale_posting",
        "ambiguous_question",
    ]
    assert report["incidents"]["passed"] is True
    assert report["predecessor"]["ok"] is True
    assert report["safety"]["submission_authorized"] is False
    assert report["safety"]["promotion_authorized"] is False


def test_failed_injected_incident_blocks_day38_entry(
    db_session,
    monkeypatch,
):
    user, _, _ = _seed_verified_day36_predecessor(db_session, monkeypatch)
    application = _day37_application(db_session, user)
    session = _day37_session(
        db_session,
        user,
        application,
        failed_incident="browser_crash",
    )

    report = build_day37_shadow_endurance_report(
        db_session,
        session_id=session.id,
        expected_revision=DAY37_REVISION,
    )

    assert report["passed"] is False
    assert report["day38_entry_eligible"] is False
    assert report["incidents"]["passed"] is False
    assert "browser_crash" in report["incidents"]["failed_incidents"]
    assert report["checks"]["all_day37_incident_recovery_gates_passed"] is False


def test_worker_restart_identity_drift_blocks_eight_hour_endurance(
    db_session,
    monkeypatch,
):
    user, _, _ = _seed_verified_day36_predecessor(db_session, monkeypatch)
    application = _day37_application(db_session, user)
    session = _day37_session(
        db_session,
        user,
        application,
        drift_worker_pid=True,
    )

    report = build_day37_shadow_endurance_report(
        db_session,
        session_id=session.id,
        expected_revision=DAY37_REVISION,
    )

    assert report["passed"] is False
    assert report["checks"]["worker_process_identity_stable"] is False
    assert report["memory"]["distinct_worker_pids"] == [4242, 4243]


def test_short_persisted_runtime_cannot_be_hidden_by_qualifying_report_shape(
    db_session,
    monkeypatch,
):
    user, _, _ = _seed_verified_day36_predecessor(db_session, monkeypatch)
    application = _day37_application(db_session, user)
    session = _day37_session(
        db_session,
        user,
        application,
        finish=START + timedelta(hours=7, minutes=59),
    )

    report = build_day37_shadow_endurance_report(
        db_session,
        session_id=session.id,
        expected_revision=DAY37_REVISION,
    )

    assert report["passed"] is False
    assert report["checks"]["persisted_elapsed_at_least_8h"] is False
    assert report["day38_entry_eligible"] is False
