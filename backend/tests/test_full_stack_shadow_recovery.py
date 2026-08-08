from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.api import shadow_runs as shadow_api
from app.models.certification import ShadowRunCycle, ShadowRunSession
from app.models.user import User
from app.tasks import shadow_runs as shadow_tasks
from tests.conftest import TestingSessionLocal


REVISION = "e" * 40


def _user(db, email="shadow-recovery@example.com"):
    user = User(
        email=email,
        hashed_password="shadow-recovery-hash",
        full_name="Shadow Recovery",
        profile_data={},
        job_preferences={},
        automation_settings={},
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user


def _session(user_id, *, status="scheduled", heartbeat=None):
    now = datetime.now(timezone.utc)
    return ShadowRunSession(
        user_id=user_id,
        candidate_revision=REVISION,
        target_evidence_type="shadow_run_4h",
        requested_duration_seconds=4 * 60 * 60,
        cycle_interval_seconds=60,
        status=status,
        started_at=now - timedelta(hours=1),
        expected_end_at=now + timedelta(hours=3),
        settle_deadline_at=now + timedelta(hours=3, minutes=45),
        last_heartbeat_at=heartbeat or now,
        final_submit_allowed=False,
        stop_requested=False,
        configuration_snapshot={},
        baseline_snapshot={},
    )


def test_active_guard_is_unique_and_terminal_state_releases_it(db_session):
    user = _user(db_session)
    first = _session(user.id)
    db_session.add(first)
    db_session.commit()
    db_session.refresh(first)
    assert first.active_guard == f"user:{user.id}"

    conflicting = _session(user.id)
    db_session.add(conflicting)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    user = db_session.query(User).filter(User.email == "shadow-recovery@example.com").one()
    first = db_session.query(ShadowRunSession).filter(ShadowRunSession.user_id == user.id).one()
    first.status = "failed"
    first.completed_at = datetime.now(timezone.utc)
    db_session.commit()
    db_session.refresh(first)
    assert first.active_guard is None

    later = _session(user.id)
    db_session.add(later)
    db_session.flush()
    assert later.active_guard == f"user:{user.id}"


def test_stalled_recovery_redispatches_only_stale_active_sessions(db_session, monkeypatch):
    user = _user(db_session)
    now = datetime.now(timezone.utc)
    stale = _session(user.id, heartbeat=now - timedelta(hours=1))
    db_session.add(stale)
    db_session.flush()

    other = _user(db_session, "fresh-shadow@example.com")
    fresh = _session(other.id, heartbeat=now)
    db_session.add(fresh)
    db_session.commit()

    stale_id = stale.id
    dispatched = []

    def fake_delay(session_id):
        dispatched.append(session_id)
        return SimpleNamespace(id=f"shadow-recovery-{session_id}")

    monkeypatch.setattr(shadow_tasks, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(shadow_tasks.run_shadow_session_cycle, "delay", fake_delay)

    result = shadow_tasks.recover_stalled_shadow_sessions()

    assert result["active_sessions_checked"] == 2
    assert result["stalled_sessions"] == 1
    assert dispatched == [stale_id]
    assert result["dispatches"] == [
        {"session_id": stale_id, "task_id": f"shadow-recovery-{stale_id}"}
    ]
    assert result["submission_authorized"] is False
    assert result["outreach_authorized"] is False


def test_stop_dispatch_failure_never_exposes_raw_broker_exception(
    auth_client,
    db_session,
    monkeypatch,
):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    session = _session(user.id, status="running")
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    secret_error = "redis://internal-user:secret-token@private-host:6379/0"

    def fail_dispatch(_session_id):
        raise RuntimeError(secret_error)

    monkeypatch.setattr(shadow_api.run_shadow_session_cycle, "delay", fail_dispatch)
    response = auth_client.post(
        f"/api/shadow-runs/{session.id}/stop",
        json={"acknowledgment": f"STOP FULL STACK SHADOW {session.id}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["dispatch_error"] == "worker_dispatch_unavailable"
    assert secret_error not in response.text
    assert "secret-token" not in response.text


def test_public_cycle_status_sanitizes_internal_error_detail(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    session = _session(user.id, status="running")
    db_session.add(session)
    db_session.flush()
    cycle = ShadowRunCycle(
        session_id=session.id,
        cycle_number=1,
        status="failed",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        completed_at=datetime.now(timezone.utc),
        scheduler_result={},
        observability_snapshot={},
        reconciliation_snapshot={},
        error_detail="provider password=super-secret infrastructure trace",
    )
    db_session.add(cycle)
    db_session.commit()

    response = auth_client.get(f"/api/shadow-runs/{session.id}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["recent_cycles"][0]["error_detail"] == "cycle_failed"
    assert "super-secret" not in response.text
    assert "infrastructure trace" not in response.text
