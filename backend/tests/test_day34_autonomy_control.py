from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job
from app.models.user import User
from app.services.autonomy_control_center import (
    build_autonomy_control_snapshot,
    change_autonomy_mode,
    reject_application_from_autonomy_queue,
)
from app.services.operator_autonomy_control import (
    AUTONOMY_CONTROL_KEY,
    MODE_DRAINING,
    MODE_PAUSED,
    MODE_RUNNING,
    autonomy_control_state,
    scheduler_control_decision,
    worker_control_decision,
)
from app.services.operator_autonomy_control_integration import install_operator_autonomy_control
from app.tasks import scraping as scraping_tasks
from app.tasks import unattended as unattended_tasks


def _user(db_session, email="day34@example.test"):
    user = User(
        email=email,
        hashed_password="day34-test-hash",
        full_name="Day 34 Operator",
        profile_data={},
        job_preferences={},
        automation_settings={},
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _job(db_session, suffix="one"):
    job = Job(
        external_id=f"day34-job-{suffix}",
        title=f"Day 34 Role {suffix}",
        company="Day 34 Employer",
        location="Ottawa, Ontario",
        url=f"https://job-boards.greenhouse.io/day34/jobs/{suffix}",
        relevance_score=0.95,
    )
    db_session.add(job)
    db_session.flush()
    return job


def _application(db_session, user, job, *, suffix="one", state="preparing", attempts=0):
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=state,
        submission_attempt_count=attempts,
        submission_idempotency_key=f"day34:{user.id}:{job.id}:{suffix}",
    )
    db_session.add(application)
    db_session.flush()
    return application


def test_operator_control_defaults_running_without_submission_authority(db_session):
    user = _user(db_session)
    state = autonomy_control_state(user)

    assert state["mode"] == MODE_RUNNING
    assert state["valid"] is True
    assert state["scheduler_admission_allowed"] is True
    assert state["prebrowser_worker_allowed"] is True
    assert state["submission_authorized"] is False


def test_invalid_persisted_operator_state_fails_closed(db_session):
    user = _user(db_session)
    user.automation_settings = {AUTONOMY_CONTROL_KEY: {"mode": "warp-speed"}}
    db_session.flush()

    state = autonomy_control_state(user)
    scheduler = scheduler_control_decision(user)
    worker = worker_control_decision(user)

    assert state["valid"] is False
    assert state["mode"] == MODE_PAUSED
    assert scheduler["allowed"] is False
    assert scheduler["code"] == "operator_control_invalid"
    assert worker["allowed"] is False
    assert worker["code"] == "operator_control_invalid"


def test_malformed_production_principal_fails_closed_without_attribute_error():
    malformed = SimpleNamespace(id=934)

    state = autonomy_control_state(malformed)
    scheduler = scheduler_control_decision(malformed)
    worker = worker_control_decision(malformed)

    assert state["valid"] is False
    assert state["mode"] == MODE_PAUSED
    assert state["submission_authorized"] is False
    assert scheduler["allowed"] is False
    assert scheduler["code"] == "operator_control_invalid"
    assert worker["allowed"] is False
    assert worker["code"] == "operator_control_invalid"


def test_malformed_shadow_principal_preserves_inherited_shadow_safety_guard(monkeypatch):
    install_operator_autonomy_control()
    malformed = SimpleNamespace(id=935)
    rank = MagicMock()
    dispatch = MagicMock()

    monkeypatch.setattr(
        scraping_tasks,
        "scheduler_settings",
        lambda _user: {
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": False,
        },
    )
    monkeypatch.setattr(
        scraping_tasks,
        "settings",
        SimpleNamespace(allow_real_application_submit=False),
    )
    monkeypatch.setattr(scraping_tasks, "rank_scheduler_candidates", rank)
    monkeypatch.setattr(
        "app.tasks.unattended.submit_unattended_application_task.apply_async",
        dispatch,
    )

    wrapped = scraping_tasks._run_scheduler_cycle_for_user
    assert getattr(wrapped, "_day34_operator_control_wrapper", False) is True
    result = wrapped(MagicMock(), malformed, shadow_session_id=441)

    assert result["reason"] == "shadow_safety_invariant_blocked"
    assert result["applications_queued"] == 0
    assert result["searched"] is False
    assert result["shadow_session_id"] == 441
    rank.assert_not_called()
    dispatch.assert_not_called()


def test_pause_drain_resume_api_is_account_scoped(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()

    paused = auth_client.post("/api/autonomy-control/pause", json={"reason": "operator test"})
    assert paused.status_code == 200, paused.text
    assert paused.json()["operator_control"]["mode"] == MODE_PAUSED

    db_session.expire_all()
    persisted = db_session.query(User).filter(User.id == user.id).one()
    assert autonomy_control_state(persisted)["mode"] == MODE_PAUSED

    drained = auth_client.post("/api/autonomy-control/drain", json={"reason": "finish existing"})
    assert drained.status_code == 200, drained.text
    assert drained.json()["operator_control"]["mode"] == MODE_DRAINING
    assert drained.json()["operator_control"]["scheduler_admission_allowed"] is False
    assert drained.json()["operator_control"]["prebrowser_worker_allowed"] is True

    resumed = auth_client.post("/api/autonomy-control/resume", json={"reason": "resume"})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["operator_control"]["mode"] == MODE_RUNNING
    assert resumed.json()["actions"]["direct_live_submit_available"] is False


def test_scheduler_run_is_blocked_by_pause_and_drain(auth_client, monkeypatch):
    dispatched = []
    monkeypatch.setattr(
        "app.api.scheduler.run_user_scheduler_cycle.delay",
        lambda user_id: dispatched.append(user_id),
    )

    assert auth_client.post("/api/autonomy-control/pause", json={}).status_code == 200
    paused = auth_client.post("/api/scheduler/run")
    assert paused.status_code == 409
    assert paused.json()["detail"]["code"] == "operator_paused"

    assert auth_client.post("/api/autonomy-control/drain", json={}).status_code == 200
    draining = auth_client.post("/api/scheduler/run")
    assert draining.status_code == 409
    assert draining.json()["detail"]["code"] == "operator_draining"
    assert dispatched == []


def test_worker_runtime_wrapper_blocks_pause_but_allows_drain_to_inherited_policy(db_session):
    user = _user(db_session)
    job = _job(db_session)
    install_operator_autonomy_control()

    change_autonomy_mode(db_session, user, mode=MODE_PAUSED, reason="test pause")
    paused = unattended_tasks.evaluate_unattended_job_policy(db_session, user, job)
    assert paused.allowed is False
    assert paused.code == "operator_paused"
    assert paused.metadata["submission_authorized"] is False

    change_autonomy_mode(db_session, user, mode=MODE_DRAINING, reason="test drain")
    drained = unattended_tasks.evaluate_unattended_job_policy(db_session, user, job)
    assert drained.code != "operator_paused"
    assert drained.metadata.get("operator_mode") == MODE_DRAINING


def test_scheduler_runtime_wrapper_admits_nothing_while_paused_or_draining(db_session):
    user = _user(db_session)
    install_operator_autonomy_control()

    for mode, code in ((MODE_PAUSED, "operator_paused"), (MODE_DRAINING, "operator_draining")):
        change_autonomy_mode(db_session, user, mode=mode, reason="runtime test")
        result = scraping_tasks._run_scheduler_cycle_for_user(db_session, user)
        assert result["skipped"] is True
        assert result["reason"] == code
        assert result["searched"] is False
        assert result["applications_queued"] == 0
        assert result["submission_authorized"] is False


def test_reject_pre_submission_application_is_canonical_withdrawal(db_session):
    user = _user(db_session)
    job = _job(db_session)
    application = _application(db_session, user, job)
    original_key = application.submission_idempotency_key
    review = ManualReviewTask(
        application_id=application.id,
        reason_code="automation_error",
        status=ManualReviewStatus.open.value,
        summary="Synthetic blocker",
        details={},
    )
    db_session.add(review)
    db_session.flush()
    handoff = ManualHandoffSession(
        application_id=application.id,
        manual_review_id=review.id,
        user_id=user.id,
        challenge_type="login",
        status=HandoffSessionStatus.awaiting_user.value,
        idempotency_key=f"day34-handoff-{application.id}",
        resume_token_hash="a" * 64,
        encrypted_resume_token="encrypted-test-token",
        resume_token_prefix="day34",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db_session.add(handoff)
    db_session.flush()

    result = reject_application_from_autonomy_queue(
        db_session,
        user,
        application_id=application.id,
        reason="Not a fit after operator review",
    )

    assert result["status"] == ApplicationStatus.withdrawn.value
    assert result["automation_state"] == ApplicationAutomationState.withdrawn.value
    assert result["submission_attempt_count"] == 0
    assert result["submission_idempotency_key"] == original_key
    assert result["submission_authorized"] is False
    assert review.status == ManualReviewStatus.dismissed.value
    assert handoff.status == HandoffSessionStatus.cancelled.value
    assert application.rejection_reason is None


def test_reject_refuses_any_application_with_submission_attempt_history(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    job = _job(db_session, suffix="attempted")
    application = _application(
        db_session,
        user,
        job,
        suffix="attempted",
        state=ApplicationAutomationState.ready_to_apply.value,
        attempts=1,
    )
    db_session.commit()

    response = auth_client.post(
        f"/api/autonomy-control/applications/{application.id}/reject",
        json={"reason": "should be blocked"},
    )
    assert response.status_code == 409

    db_session.expire_all()
    persisted = db_session.query(Application).filter(Application.id == application.id).one()
    assert persisted.status == ApplicationStatus.pending
    assert persisted.automation_state == ApplicationAutomationState.ready_to_apply.value
    assert persisted.submission_attempt_count == 1


def test_control_snapshot_contains_day34_domains_and_no_submit_action(db_session):
    user = _user(db_session)
    job = _job(db_session, suffix="snapshot")
    application = _application(db_session, user, job, suffix="snapshot")
    review = ManualReviewTask(
        application_id=application.id,
        reason_code="login_required",
        status=ManualReviewStatus.open.value,
        summary="Sign in required",
        details={},
    )
    db_session.add(review)
    db_session.flush()
    handoff = ManualHandoffSession(
        application_id=application.id,
        manual_review_id=review.id,
        user_id=user.id,
        challenge_type="login",
        status=HandoffSessionStatus.awaiting_user.value,
        idempotency_key=f"day34-snapshot-handoff-{application.id}",
        resume_token_hash="b" * 64,
        encrypted_resume_token="encrypted-test-token",
        resume_token_prefix="snap",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    db_session.add(handoff)
    db_session.flush()

    snapshot = build_autonomy_control_snapshot(db_session, user)

    for key in (
        "readiness",
        "adapters",
        "caps",
        "queue",
        "blockers",
        "handoffs",
        "evidence",
        "kill_switches",
        "actions",
    ):
        assert key in snapshot
    assert snapshot["queue"]["count"] >= 1
    assert snapshot["blockers"]["count"] >= 1
    assert snapshot["handoffs"]["count"] == 1
    assert snapshot["actions"]["direct_live_submit_available"] is False
    assert snapshot["invariants"]["control_centre_cannot_authorize_submission"] is True
