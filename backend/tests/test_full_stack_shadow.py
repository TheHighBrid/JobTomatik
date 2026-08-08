from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.api import shadow_runs as shadow_api
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
)
from app.models.certification import CertificationEvidence, ShadowRunSession
from app.models.intelligence import AgentRun
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services import full_stack_shadow
from app.services.full_stack_shadow import (
    ShadowCampaignError,
    create_shadow_session,
    execute_shadow_cycle,
    record_shadow_certification_evidence,
    request_shadow_stop,
)


REVISION = "d" * 40
STARTED = datetime(2026, 8, 8, 3, 30, tzinfo=timezone.utc)


def _user(db, email: str = "shadow-owner@example.com") -> User:
    user = User(
        email=email,
        hashed_password="shadow-test-hash",
        full_name="Shadow Owner",
        profile_data={},
        job_preferences={},
        automation_settings={},
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _preflight(target: str = "shadow_run_4h") -> dict:
    seconds = full_stack_shadow.TARGET_SECONDS[target]
    return {
        "ok": True,
        "checks": {},
        "blockers": [],
        "candidate_revision": REVISION,
        "target_evidence_type": target,
        "requested_duration_seconds": seconds,
        "expected_start_acknowledgment": (
            f"START FULL STACK SHADOW {target} {REVISION[:12]}"
        ),
        "scheduler": {
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": True,
        },
        "operations": {
            "autopilot_enabled": True,
            "global_kill_switch": False,
            "disabled_platforms": [],
        },
        "runtime": {
            "allow_real_application_submit": False,
            "allow_real_followup_send": False,
        },
        "invariants": {
            "final_submit_allowed": False,
            "runtime_settings_mutated": False,
            "outreach_authorized": False,
            "adapter_maturity_mutated": False,
        },
    }


def _install_safe_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        full_stack_shadow,
        "get_settings",
        lambda: SimpleNamespace(
            allow_real_application_submit=False,
            allow_real_followup_send=False,
        ),
    )
    monkeypatch.setattr(full_stack_shadow, "current_revision", lambda: REVISION)
    monkeypatch.setattr(
        full_stack_shadow,
        "full_stack_shadow_preflight",
        lambda db, user, target_evidence_type="shadow_run_4h": _preflight(
            target_evidence_type
        ),
    )
    monkeypatch.setattr(
        full_stack_shadow,
        "_observability_report",
        lambda db, user_id, window_hours: {
            "summary": {"incident_count": 0, "critical_incident_count": 0},
            "activity": {},
            "incidents": [],
            "unavailable": False,
        },
    )


def _create_session(db, user: User, *, target: str = "shadow_run_4h") -> ShadowRunSession:
    session = create_shadow_session(
        db,
        user_id=user.id,
        target_evidence_type=target,
        acknowledgment=f"START FULL STACK SHADOW {target} {REVISION[:12]}",
        cycle_interval_seconds=60,
        now=STARTED,
    )
    db.flush()
    return session


def _qualifying_scheduler_runner(now: datetime):
    def runner(db, user, *, shadow_session_id=None):
        job = Job(
            external_id=f"shadow-job-{shadow_session_id}",
            title="Shadow QA Engineer",
            company="Evidence Labs",
            location="Remote",
            url="https://example.com/jobs/shadow-qa",
            source=JobSource.manual,
            status=JobStatus.approved,
            relevance_score=0.95,
            raw_data={},
        )
        db.add(job)
        db.flush()
        app = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.pending,
            automation_state=ApplicationAutomationState.ready_to_apply.value,
            submission_idempotency_key=(
                f"shadow:{shadow_session_id}:application:{job.id}"
            ),
            submission_attempt_count=1,
        )
        db.add(app)
        db.flush()
        db.add(
            ApplicationEvent(
                application_id=app.id,
                event_type="application_created",
                from_state=None,
                to_state=ApplicationAutomationState.ready_to_apply.value,
                payload={
                    "source": "full_stack_shadow_scheduler",
                    "shadow_session_id": shadow_session_id,
                    "dry_run": True,
                },
                created_at=now,
            )
        )
        db.add(
            AgentRun(
                user_id=user.id,
                objective="Synthetic correlated shadow discovery",
                status="completed",
                autonomy_level="reviewed",
                risk_level="low",
                requires_approval=False,
                plan=[],
                run_context={"pipeline": "public_ats_discovery_v1"},
                result={
                    "shadow_session_id": shadow_session_id,
                    "saved": 1,
                    "total_found": 1,
                },
                started_at=now,
                completed_at=now,
                created_at=now,
            )
        )
        db.flush()
        return {
            "user_id": user.id,
            "reason": "scheduler_cycle_completed",
            "searched": True,
            "search_task_id": "synthetic-search-task",
            "applications_queued": 1,
            "application_ids_queued": [app.id],
            "real_submission_enabled": False,
            "dry_run": True,
            "shadow_session_id": shadow_session_id,
        }

    return runner


def test_start_requires_exact_ack_and_only_one_active_campaign(db_session, monkeypatch):
    _install_safe_runtime(monkeypatch)
    user = _user(db_session)

    with pytest.raises(ShadowCampaignError, match="Exact shadow acknowledgment"):
        create_shadow_session(
            db_session,
            user_id=user.id,
            target_evidence_type="shadow_run_4h",
            acknowledgment="START",
            now=STARTED,
        )

    session = _create_session(db_session, user)
    assert session.status == "scheduled"
    assert session.final_submit_allowed is False

    with pytest.raises(ShadowCampaignError, match="Active shadow campaign already exists"):
        _create_session(db_session, user)


def test_cycle_correlation_settling_and_final_qualification(db_session, monkeypatch):
    _install_safe_runtime(monkeypatch)
    user = _user(db_session)
    session = _create_session(db_session, user)

    first = execute_shadow_cycle(
        db_session,
        session_id=session.id,
        scheduler_runner=_qualifying_scheduler_runner(STARTED + timedelta(minutes=1)),
        now=STARTED + timedelta(minutes=1),
    )
    db_session.flush()
    assert first["status"] == "running"
    assert first["schedule_next"] is True
    assert session.cycles_completed == 1
    assert session.cycles_failed == 0

    app = db_session.query(Application).filter(Application.user_id == user.id).one()
    app.automation_state = ApplicationAutomationState.preparing.value
    db_session.flush()

    at_duration = STARTED + timedelta(hours=4)
    settling = execute_shadow_cycle(
        db_session,
        session_id=session.id,
        scheduler_runner=_qualifying_scheduler_runner(at_duration),
        now=at_duration,
    )
    assert settling["status"] == "settling"
    assert settling["schedule_next"] is True
    assert settling["active_application_ids"] == [app.id]

    app.automation_state = ApplicationAutomationState.ready_to_apply.value
    db_session.flush()
    completed = execute_shadow_cycle(
        db_session,
        session_id=session.id,
        scheduler_runner=_qualifying_scheduler_runner(at_duration),
        now=at_duration + timedelta(minutes=1),
    )
    db_session.flush()
    assert completed["status"] == "completed"
    assert completed["report"]["qualification_eligible"] is True
    assert completed["report"]["quality"]["discovery_path_observed"] is True
    assert completed["report"]["quality"]["application_path_observed"] is True
    assert completed["report"]["safety"]["final_submit_clicked"] is False
    assert session.report_sha256


def test_scheduler_real_submission_signal_fails_closed(db_session, monkeypatch):
    _install_safe_runtime(monkeypatch)
    user = _user(db_session)
    session = _create_session(db_session, user)

    def unsafe_runner(db, user, *, shadow_session_id=None):
        return {
            "applications_queued": 0,
            "application_ids_queued": [],
            "searched": False,
            "real_submission_enabled": True,
            "dry_run": True,
            "shadow_session_id": shadow_session_id,
        }

    result = execute_shadow_cycle(
        db_session,
        session_id=session.id,
        scheduler_runner=unsafe_runner,
        now=STARTED + timedelta(minutes=1),
    )
    assert result["status"] == "running"
    assert session.cycles_failed == 1
    cycle = session.id
    assert db_session.query(ShadowRunSession).filter(ShadowRunSession.id == cycle).one().final_submit_allowed is False


def test_stop_requires_exact_acknowledgment(db_session, monkeypatch):
    _install_safe_runtime(monkeypatch)
    user = _user(db_session)
    session = _create_session(db_session, user)

    with pytest.raises(ShadowCampaignError, match="Exact shadow acknowledgment"):
        request_shadow_stop(
            db_session,
            user_id=user.id,
            session_id=session.id,
            acknowledgment="STOP",
        )

    stopped = request_shadow_stop(
        db_session,
        user_id=user.id,
        session_id=session.id,
        acknowledgment=f"STOP FULL STACK SHADOW {session.id}",
    )
    assert stopped.status == "stopping"
    assert stopped.stop_requested is True


def test_qualified_campaign_creates_only_unreviewed_hash_bound_evidence(db_session, monkeypatch):
    _install_safe_runtime(monkeypatch)
    user = _user(db_session)
    session = _create_session(db_session, user)
    execute_shadow_cycle(
        db_session,
        session_id=session.id,
        scheduler_runner=_qualifying_scheduler_runner(STARTED + timedelta(minutes=1)),
        now=STARTED + timedelta(minutes=1),
    )
    execute_shadow_cycle(
        db_session,
        session_id=session.id,
        scheduler_runner=_qualifying_scheduler_runner(STARTED + timedelta(hours=4)),
        now=STARTED + timedelta(hours=4, minutes=1),
    )
    db_session.flush()
    assert session.status == "completed"

    evidence, duplicate = record_shadow_certification_evidence(
        db_session,
        user_id=user.id,
        session_id=session.id,
    )
    db_session.flush()
    assert duplicate is False
    assert evidence.evidence_type == "shadow_run_4h"
    assert evidence.review_status == "unreviewed"
    assert evidence.status == "passed"
    assert evidence.evidence_metadata["full_stack_shadow_session"] is True
    assert evidence.evidence_metadata["final_submit_clicked"] is False
    assert evidence.evidence_metadata["submission_authorized"] is False
    assert evidence.evidence_metadata["outreach_authorized"] is False

    same, duplicate = record_shadow_certification_evidence(
        db_session,
        user_id=user.id,
        session_id=session.id,
    )
    assert duplicate is True
    assert same.id == evidence.id

    session.certification_evidence_id = None
    session.final_report = {**dict(session.final_report), "quality": {"tampered": True}}
    db_session.flush()
    with pytest.raises(ShadowCampaignError, match="report hash mismatch"):
        record_shadow_certification_evidence(
            db_session,
            user_id=user.id,
            session_id=session.id,
        )


def test_shadow_campaign_api_is_account_scoped(auth_client, db_session, monkeypatch):
    _install_safe_runtime(monkeypatch)
    owner = _user(db_session, "campaign-owner@example.com")
    session = _create_session(db_session, owner)
    db_session.commit()

    get_other = auth_client.get(f"/api/shadow-runs/{session.id}")
    assert get_other.status_code == 404
    stop_other = auth_client.post(
        f"/api/shadow-runs/{session.id}/stop",
        json={"acknowledgment": f"STOP FULL STACK SHADOW {session.id}"},
    )
    assert stop_other.status_code == 409
    evidence_other = auth_client.post(f"/api/shadow-runs/{session.id}/record-evidence")
    assert evidence_other.status_code == 409


def test_start_api_marks_session_failed_when_initial_dispatch_is_unavailable(
    auth_client,
    db_session,
    monkeypatch,
):
    _install_safe_runtime(monkeypatch)
    monkeypatch.setattr(
        shadow_api,
        "full_stack_shadow_preflight",
        lambda db, user, target_evidence_type="shadow_run_4h": _preflight(
            target_evidence_type
        ),
    )
    monkeypatch.setattr(
        shadow_api.run_shadow_session_cycle,
        "delay",
        lambda session_id: (_ for _ in ()).throw(RuntimeError("synthetic broker outage")),
    )

    response = auth_client.post(
        "/api/shadow-runs",
        json={
            "target_evidence_type": "shadow_run_4h",
            "cycle_interval_seconds": 60,
            "acknowledgment": f"START FULL STACK SHADOW shadow_run_4h {REVISION[:12]}",
        },
    )
    assert response.status_code == 503, response.text
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    session = (
        db_session.query(ShadowRunSession)
        .filter(ShadowRunSession.user_id == user.id)
        .one()
    )
    assert session.status == "failed"
    assert "shadow_dispatch_failed" in str(session.failure_reason)
    assert db_session.query(CertificationEvidence).count() == 0
