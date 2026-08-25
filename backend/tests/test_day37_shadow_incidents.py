from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.certification import ShadowRunCycle, ShadowRunSession
from app.models.user import User
from app.services import day37_shadow_incidents
from app.services.day37_shadow_incidents import (
    DAY37_INCIDENT_PLAN,
    _ambiguous_question_drill,
    _source_outage_drill,
    day37_incident_timeline,
    next_due_day37_incident,
    run_due_day37_incident,
)
from app.tasks import shadow_runs as shadow_tasks


START = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _user(db_session) -> User:
    user = User(
        email="day37-incidents@example.test",
        hashed_password="hash",
        automation_settings={},
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _session(db_session, user: User) -> ShadowRunSession:
    session = ShadowRunSession(
        user_id=user.id,
        candidate_revision="7" * 40,
        target_evidence_type="shadow_run_8h",
        requested_duration_seconds=8 * 60 * 60,
        cycle_interval_seconds=15 * 60,
        status="running",
        started_at=START,
        expected_end_at=START + timedelta(hours=8),
        settle_deadline_at=START + timedelta(hours=8, minutes=45),
        last_heartbeat_at=START,
        final_submit_allowed=False,
        stop_requested=False,
        configuration_snapshot={},
        baseline_snapshot={},
    )
    db_session.add(session)
    db_session.flush()
    return session


def _retain_incident(
    db_session,
    session: ShadowRunSession,
    *,
    cycle_number: int,
    incident_type: str,
    status: str = "passed",
) -> ShadowRunCycle:
    plan = next(item for item in DAY37_INCIDENT_PLAN if item["incident_type"] == incident_type)
    cycle = ShadowRunCycle(
        session_id=session.id,
        cycle_number=cycle_number,
        status="completed",
        started_at=START + timedelta(seconds=int(plan["minimum_elapsed_seconds"])),
        completed_at=START + timedelta(seconds=int(plan["minimum_elapsed_seconds"]) + 10),
        scheduler_result={"dry_run": True, "real_submission_enabled": False},
        observability_snapshot={
            "day37_incident": {
                "version": day37_shadow_incidents.DAY37_INCIDENT_VERSION,
                "incident_type": incident_type,
                "planned_minimum_elapsed_seconds": int(plan["minimum_elapsed_seconds"]),
                "observed_elapsed_seconds": float(plan["minimum_elapsed_seconds"]),
                "injected_at": (
                    START + timedelta(seconds=int(plan["minimum_elapsed_seconds"]))
                ).isoformat(),
                "status": status,
                "recovery_contract": plan["recovery_contract"],
                "observed": {},
                "error_code": None,
                "breaker_state": {"allowed": True, "code": "circuit_breaker_closed"},
                "safety": {
                    "real_submission_requested": False,
                    "outreach_requested": False,
                    "adapter_maturity_mutated": False,
                    "browser_process_kill_requested": False,
                },
            }
        },
        reconciliation_snapshot={},
    )
    db_session.add(cycle)
    db_session.flush()
    return cycle


def test_source_outage_drill_uses_production_reducer_and_keeps_other_source():
    result = _source_outage_drill()

    assert result["passed"] is True
    assert result["observed"]["failed_source_count"] == 1
    assert result["observed"]["successful_source_count"] == 1
    assert result["observed"]["surviving_result_count"] == 1
    assert result["observed"]["raw_exception_retained"] is False


def test_ambiguous_question_drill_never_invents_an_answer():
    result = _ambiguous_question_drill()

    assert result["passed"] is True
    assert result["observed"]["canonical_key"] == "custom.unclassified"
    assert result["observed"]["can_autofill"] is False
    assert result["observed"]["answer_generated"] is False
    assert result["observed"]["review_reason"] == "ambiguous_question"


def test_incidents_become_due_in_plan_order_and_only_once(db_session):
    user = _user(db_session)
    session = _session(db_session, user)

    assert next_due_day37_incident(
        db_session,
        session,
        now=START + timedelta(minutes=59),
    ) is None

    first = next_due_day37_incident(
        db_session,
        session,
        now=START + timedelta(hours=1),
    )
    assert first["incident_type"] == "source_outage"
    _retain_incident(db_session, session, cycle_number=1, incident_type="source_outage")

    second = next_due_day37_incident(
        db_session,
        session,
        now=START + timedelta(hours=3),
    )
    assert second["incident_type"] == "browser_crash"
    _retain_incident(db_session, session, cycle_number=2, incident_type="browser_crash")

    third = next_due_day37_incident(
        db_session,
        session,
        now=START + timedelta(hours=5),
    )
    assert third["incident_type"] == "stale_posting"
    _retain_incident(db_session, session, cycle_number=3, incident_type="stale_posting")

    fourth = next_due_day37_incident(
        db_session,
        session,
        now=START + timedelta(hours=6, minutes=30),
    )
    assert fourth["incident_type"] == "ambiguous_question"
    _retain_incident(db_session, session, cycle_number=4, incident_type="ambiguous_question")

    assert next_due_day37_incident(
        db_session,
        session,
        now=START + timedelta(hours=7, minutes=30),
    ) is None
    assert [item["incident_type"] for item in day37_incident_timeline(db_session, session_id=session.id)] == [
        "source_outage",
        "browser_crash",
        "stale_posting",
        "ambiguous_question",
    ]


def test_failed_incident_is_retained_as_attempted_and_never_silently_retried(db_session):
    user = _user(db_session)
    session = _session(db_session, user)
    _retain_incident(
        db_session,
        session,
        cycle_number=1,
        incident_type="source_outage",
        status="failed",
    )

    due = next_due_day37_incident(
        db_session,
        session,
        now=START + timedelta(hours=2),
    )

    assert due is None
    timeline = day37_incident_timeline(db_session, session_id=session.id)
    assert len(timeline) == 1
    assert timeline[0]["incident_type"] == "source_outage"
    assert timeline[0]["status"] == "failed"


def test_run_due_incident_records_bounded_breaker_and_safety_state(db_session):
    user = _user(db_session)
    session = _session(db_session, user)

    result = run_due_day37_incident(
        db_session,
        session,
        now=START + timedelta(hours=1),
        runner=lambda incident_type: {
            "passed": incident_type == "source_outage",
            "observed": {"fixture": True, "browser_process_kill_requested": False},
        },
    )

    assert result["incident_type"] == "source_outage"
    assert result["status"] == "passed"
    assert result["breaker_state"]["allowed"] is True
    assert result["breaker_state"]["code"] == "circuit_breaker_closed"
    assert result["safety"] == {
        "real_submission_requested": False,
        "outreach_requested": False,
        "adapter_maturity_mutated": False,
        "browser_process_kill_requested": False,
    }


def test_cycle_attachment_persists_incident_inside_observability_snapshot(
    db_session,
    monkeypatch,
):
    user = _user(db_session)
    session = _session(db_session, user)
    cycle = ShadowRunCycle(
        session_id=session.id,
        cycle_number=5,
        status="completed",
        started_at=START + timedelta(hours=1),
        completed_at=START + timedelta(hours=1, seconds=10),
        scheduler_result={"dry_run": True, "real_submission_enabled": False},
        observability_snapshot={"summary": {"incident_count": 0}},
        reconciliation_snapshot={},
    )
    db_session.add(cycle)
    db_session.flush()

    retained = {
        "version": day37_shadow_incidents.DAY37_INCIDENT_VERSION,
        "incident_type": "source_outage",
        "planned_minimum_elapsed_seconds": 3600,
        "observed_elapsed_seconds": 3600.0,
        "injected_at": (START + timedelta(hours=1)).isoformat(),
        "status": "passed",
        "recovery_contract": "independent_source_failure_isolated",
        "observed": {"fixture": True},
        "error_code": None,
        "breaker_state": {"allowed": True, "code": "circuit_breaker_closed"},
        "safety": {
            "real_submission_requested": False,
            "outreach_requested": False,
            "adapter_maturity_mutated": False,
            "browser_process_kill_requested": False,
        },
    }
    monkeypatch.setattr(
        day37_shadow_incidents,
        "run_due_day37_incident",
        lambda *_args, **_kwargs: retained,
    )

    result = shadow_tasks._attach_due_day37_incident(
        db_session,
        {"status": "running", "schedule_next": True},
        session.id,
    )
    db_session.flush()
    db_session.refresh(cycle)

    assert result["day37_incident"] == {
        "incident_type": "source_outage",
        "status": "passed",
        "recovery_contract": "independent_source_failure_isolated",
    }
    assert cycle.observability_snapshot["summary"] == {"incident_count": 0}
    assert cycle.observability_snapshot["day37_incident"] == retained
