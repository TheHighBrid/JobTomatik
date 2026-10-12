"""JT5 reservation concurrency and worker outcome integration tests."""
from unittest.mock import MagicMock


from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.submission_integrity import SubmissionAttempt, SubmissionAttemptStatus
from app.models.user import User
from app.services.application_attempt_jt5 import reserve_jt5_attempt
from app.services.application_attempt_lifecycle_jt5 import claim_jt5_attempt
from app.services.application_execution_gate import ApplyDecision
from app.services.submission_integrity import (
    build_submission_identity_aliases,
    claim_submission_identity_aliases,
)
import app.api.jt5_applications as jt5_api
from app.tasks.jt5_execution import execute_reserved_application
from tests.conftest import TestingSessionLocal


def _user(db, *, email="jt5-owner@example.com"):
    item = User(
        email=email,
        hashed_password="not-used",
        full_name="JT5 Owner",
    )
    db.add(item)
    db.flush()
    return item


def _job(db, *, url="https://boards.greenhouse.io/example/jobs/1"):
    item = Job(
        title="Software Engineer",
        company="Example Co",
        url=url,
        source=JobSource.greenhouse,
        status=JobStatus.approved,
        raw_data={},
    )
    db.add(item)
    db.flush()
    return item


def _application(db, user, job):
    item = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.ready_to_apply.value,
        source_listing_url=job.url,
        application_target_url=job.url,
        submission_idempotency_key=f"jt5-test:{user.id}:{job.id}",
        cover_letter="Reviewed letter",
    )
    db.add(item)
    db.flush()
    claim_submission_identity_aliases(
        db,
        item,
        build_submission_identity_aliases(job, application=item),
    )
    return item


def test_second_reserve_while_queued_is_in_progress(db_session):
    user = _user(db_session)
    application = _application(db_session, user, _job(db_session))

    first_decision, first_attempt = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    db_session.commit()

    second_decision, second_attempt = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )

    assert first_decision.decision is ApplyDecision.EXECUTE
    assert first_attempt is not None
    assert second_decision.decision is ApplyDecision.IN_PROGRESS
    assert second_decision.reason == "attempt_in_progress"
    assert db_session.query(SubmissionAttempt).count() == 1


def test_succeeded_attempt_blocks_new_reserve(db_session):
    user = _user(db_session)
    application = _application(db_session, user, _job(db_session))
    decision, attempt = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    assert decision.decision is ApplyDecision.EXECUTE
    attempt.status = SubmissionAttemptStatus.succeeded.value
    db_session.commit()

    next_decision, next_attempt = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    assert next_decision.decision is ApplyDecision.ALREADY_CONFIRMED
    assert next_attempt is None
    assert db_session.query(SubmissionAttempt).count() == 1


def test_uncertain_attempt_requires_reconcile(db_session):
    user = _user(db_session)
    application = _application(db_session, user, _job(db_session))
    _, attempt = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    attempt.status = SubmissionAttemptStatus.uncertain.value
    db_session.commit()

    decision, _ = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    assert decision.decision is ApplyDecision.RECONCILE
    assert decision.reason == "prior_outcome_uncertain"


def test_claim_is_single_owner(db_session):
    user = _user(db_session)
    application = _application(db_session, user, _job(db_session))
    _, attempt = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    db_session.commit()
    reference = attempt.reference

    first = claim_jt5_attempt(db_session, application.id, reference)
    db_session.commit()
    assert first is not None
    assert first.status == SubmissionAttemptStatus.in_progress.value

    second = claim_jt5_attempt(db_session, application.id, reference)
    assert second is None
    db_session.refresh(attempt)
    assert attempt.status == SubmissionAttemptStatus.in_progress.value


def test_api_reserve_then_second_returns_in_progress(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    application = _application(db_session, user, _job(db_session))
    db_session.commit()

    first = auth_client.post(f"/api/applications/{application.id}/jt5/reserve")
    second = auth_client.post(f"/api/applications/{application.id}/jt5/reserve")

    assert first.status_code == 200
    assert first.json()["status"] == "reserved"
    assert first.json()["execution_contract"] == "jt5"
    assert second.status_code == 200
    assert second.json()["status"] == "in_progress"
    assert db_session.query(SubmissionAttempt).count() == 1


def test_api_apply_dispatches_without_approval(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    application = _application(db_session, user, _job(db_session))
    db_session.commit()

    response = auth_client.post(f"/api/applications/{application.id}/jt5/apply")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["dispatch_status"] == "dispatched"
    assert body["execution_contract"] == "jt5"
    assert body["automatic_retry_allowed"] is False
    assert body["task_id"] == "test-task-id"
    attempt = (
        db_session.query(SubmissionAttempt)
        .filter(SubmissionAttempt.reference == body["attempt_reference"])
        .one()
    )
    assert (attempt.attempt_metadata or {}).get("execution_contract") == "jt5"
    assert attempt.task_id.startswith("reserved-")
    assert attempt.attempt_metadata["broker_task_id"] == "test-task-id"


def test_worker_confirmed_outcome(monkeypatch, db_session):
    user = _user(db_session, email="jt5-worker-confirmed@example.com")
    application = _application(db_session, user, _job(db_session))
    _, attempt = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    db_session.commit()
    reference = attempt.reference

    async def fake_fill(*args, **kwargs):
        return {
            "success": True,
            "submitted_at": "2026-10-11T20:00:00",
            "submission_confirmed": True,
            "log": [{"action": "submit clicked"}],
            "confirmation_evidence": [{"is_sufficient": True}],
        }

    monkeypatch.setattr(
        "app.tasks.jt5_execution.fill_and_submit_application",
        fake_fill,
    )

    result = execute_reserved_application.run(application.id, reference)
    assert result["outcome"] == "confirmed"
    assert result["automatic_retry_allowed"] is False

    db_session.expire_all()
    application = db_session.query(Application).filter(Application.id == application.id).one()
    attempt = (
        db_session.query(SubmissionAttempt)
        .filter(SubmissionAttempt.reference == reference)
        .one()
    )
    assert application.automation_state == ApplicationAutomationState.confirmed.value
    assert application.status == ApplicationStatus.applied
    assert attempt.status == SubmissionAttemptStatus.succeeded.value




def test_worker_uses_resolved_target_with_supervised_metadata(monkeypatch, db_session):
    user = _user(db_session, email="jt5-resolved-target@example.com")
    job = _job(db_session)
    application = _application(db_session, user, job)
    target_url = application.application_target_url
    job.url = "https://www.linkedin.com/jobs/view/123456"
    job.raw_data = {
        "supervised_target_metadata": {
            "platform": "lever",
            "verified": True,
            "identity_hash": "bound-target",
        }
    }
    _, attempt = reserve_jt5_attempt(
        db_session, application_id=application.id, authenticated_user_id=user.id
    )
    db_session.commit()

    calls = []

    async def fake_fill(job_url, *args, **kwargs):
        calls.append((job_url, kwargs))
        return {
            "success": False,
            "error": "pre-submit test boundary",
            "final_submit_attempted": False,
            "pre_submit_failure_verified": True,
            "log": [],
        }

    monkeypatch.setattr("app.tasks.jt5_execution.fill_and_submit_application", fake_fill)
    monkeypatch.setattr("app.tasks.jt5_execution._record_result_evidence", lambda *args, **kwargs: None)

    result = execute_reserved_application.run(application.id, attempt.reference)

    assert result["outcome"] == "failed_pre_submit"
    assert len(calls) == 1
    assert calls[0][0] == target_url
    assert calls[0][1]["supervised_target"]["identity_hash"] == "bound-target"
    assert calls[0][1]["dry_run"] is False


def test_worker_rejects_reservation_identity_drift_before_browser(monkeypatch, db_session):
    user = _user(db_session, email="jt5-identity-drift@example.com")
    application = _application(db_session, user, _job(db_session))
    _, attempt = reserve_jt5_attempt(
        db_session, application_id=application.id, authenticated_user_id=user.id
    )
    attempt.identity_digest = "stale-identity-digest"
    db_session.commit()

    async def forbidden_fill(*args, **kwargs):
        raise AssertionError("browser must not start after reservation identity drift")

    monkeypatch.setattr("app.tasks.jt5_execution.fill_and_submit_application", forbidden_fill)
    result = execute_reserved_application.run(application.id, attempt.reference)

    assert result["outcome"] == "failed_pre_submit"
    assert result["error"] == "reservation_identity_changed"
    db_session.expire_all()
    saved_attempt = db_session.query(SubmissionAttempt).filter_by(id=attempt.id).one()
    saved_application = db_session.query(Application).filter_by(id=application.id).one()
    assert saved_attempt.status == SubmissionAttemptStatus.failed.value
    assert saved_application.automation_state == ApplicationAutomationState.ready_to_apply.value


def test_worker_failed_pre_submit_is_retryable_state(monkeypatch, db_session):
    user = _user(db_session, email="jt5-worker-fail@example.com")
    application = _application(db_session, user, _job(db_session))
    _, attempt = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    db_session.commit()
    reference = attempt.reference

    async def fake_fill(*args, **kwargs):
        return {
            "success": False,
            "error": "missing required field",
            "requires_manual_review": True,
            "final_submit_attempted": False,
            "pre_submit_failure_verified": True,
            "log": [{"action": "missing_field"}],
        }

    monkeypatch.setattr(
        "app.tasks.jt5_execution.fill_and_submit_application",
        fake_fill,
    )
    monkeypatch.setattr(
        "app.tasks.jt5_execution._record_result_evidence",
        lambda *args, **kwargs: None,
    )

    result = execute_reserved_application.run(application.id, reference)
    assert result["outcome"] == "failed_pre_submit"

    db_session.expire_all()
    application = db_session.query(Application).filter(Application.id == application.id).one()
    attempt = (
        db_session.query(SubmissionAttempt)
        .filter(SubmissionAttempt.reference == reference)
        .one()
    )
    assert application.automation_state == ApplicationAutomationState.ready_to_apply.value
    assert attempt.status == SubmissionAttemptStatus.failed.value

    # A failed pre-submit attempt is not active; a new reserve is allowed.
    decision, new_attempt = reserve_jt5_attempt(
        db_session,
        application_id=application.id,
        authenticated_user_id=user.id,
    )
    assert decision.decision is ApplyDecision.EXECUTE
    assert new_attempt is not None
    assert new_attempt.reference != reference


def test_jt5_dispatch_failure_requires_reconciliation(auth_client, db_session, monkeypatch):
    import app.api.jt5_applications as jt5_api

    user = db_session.query(User).filter(User.email == "test@example.com").one()
    application = _application(db_session, user, _job(db_session))
    db_session.commit()

    def ambiguous_publish(*args, **kwargs):
        raise ConnectionError("broker acknowledgement lost")

    monkeypatch.setattr(jt5_api.execute_reserved_application, "apply_async", ambiguous_publish)
    response = auth_client.post(f"/api/applications/{application.id}/jt5/apply")
    assert response.status_code == 503
    attempts = db_session.query(SubmissionAttempt).filter(
        SubmissionAttempt.application_id == application.id
    ).all()
    assert len(attempts) == 1
    assert attempts[0].status == SubmissionAttemptStatus.queued.value
    db_session.expire_all()
    assert db_session.query(SubmissionAttempt).filter_by(id=attempts[0].id).one().attempt_metadata["dispatch_status"] == "reconciliation_required"

    status = auth_client.get(f"/api/applications/{application.id}/jt5/status")
    assert status.status_code == 200
    assert status.json()["latest_attempt"]["dispatch_status"] == "reconciliation_required"

    again = auth_client.post(f"/api/applications/{application.id}/jt5/apply")
    assert again.status_code == 200
    assert again.json()["status"] == "in_progress"
    assert db_session.query(SubmissionAttempt).filter(
        SubmissionAttempt.application_id == application.id
    ).count() == 1


def test_dispatch_ack_after_worker_completion_does_not_reopen_attempt(
    auth_client, db_session, monkeypatch
):
    """Broker ACK can arrive after worker has completed its transaction."""
    import app.api.jt5_applications as jt5_api

    user = db_session.query(User).filter(User.email == "test@example.com").one()
    application = _application(db_session, user, _job(db_session))
    db_session.commit()

    def finish_before_ack(*args, **kwargs):
        session = TestingSessionLocal()
        try:
            attempt = (
                session.query(SubmissionAttempt)
                .filter(SubmissionAttempt.application_id == application.id)
                .one()
            )
            attempt.status = SubmissionAttemptStatus.succeeded.value
            attempt.attempt_metadata = {
                **(attempt.attempt_metadata or {}),
                "dispatch_status": "worker_completed",
            }
            session.commit()
        finally:
            session.close()
        return type("Result", (), {"id": "ack-after-worker"})()

    monkeypatch.setattr(jt5_api.execute_reserved_application, "apply_async", finish_before_ack)
    response = auth_client.post(f"/api/applications/{application.id}/jt5/apply")
    assert response.status_code == 200
    db_session.expire_all()
    attempt = db_session.query(SubmissionAttempt).filter_by(application_id=application.id).one()
    assert attempt.status == SubmissionAttemptStatus.succeeded.value
    assert attempt.attempt_metadata["dispatch_status"] == "worker_completed"
    assert attempt.attempt_metadata["broker_task_id"] == "ack-after-worker"


def test_dispatch_error_after_worker_completion_does_not_reopen_attempt(
    auth_client, db_session, monkeypatch
):
    """A lost ACK must not change a terminal worker outcome to queued."""
    import app.api.jt5_applications as jt5_api

    user = db_session.query(User).filter(User.email == "test@example.com").one()
    application = _application(db_session, user, _job(db_session))
    db_session.commit()

    def finish_then_raise(*args, **kwargs):
        session = TestingSessionLocal()
        try:
            attempt = (
                session.query(SubmissionAttempt)
                .filter(SubmissionAttempt.application_id == application.id)
                .one()
            )
            attempt.status = SubmissionAttemptStatus.succeeded.value
            attempt.attempt_metadata = {
                **(attempt.attempt_metadata or {}),
                "dispatch_status": "worker_completed",
            }
            session.commit()
        finally:
            session.close()
        raise ConnectionError("ACK lost after worker completion")

    monkeypatch.setattr(jt5_api.execute_reserved_application, "apply_async", finish_then_raise)
    response = auth_client.post(f"/api/applications/{application.id}/jt5/apply")
    assert response.status_code == 503
    db_session.expire_all()
    attempt = db_session.query(SubmissionAttempt).filter_by(application_id=application.id).one()
    assert attempt.status == SubmissionAttemptStatus.succeeded.value
    assert attempt.attempt_metadata["dispatch_status"] == "worker_completed"
    assert attempt.attempt_metadata["dispatch_error_type"] == "ConnectionError"


def test_worker_exception_after_confirmed_commit_does_not_demote_application(
    monkeypatch, db_session
):
    """Failure in a post-commit path cannot reverse confirmed application state."""
    import app.tasks.jt5_execution as jt5_task

    user = _user(db_session, email="jt5-terminal-exception@example.com")
    application = _application(db_session, user, _job(db_session))
    _, attempt = reserve_jt5_attempt(
        db_session, application_id=application.id, authenticated_user_id=user.id
    )
    db_session.commit()
    reference = attempt.reference

    def fail_after_confirmed_commit(*args, **kwargs):
        session = TestingSessionLocal()
        try:
            current_attempt = session.query(SubmissionAttempt).filter_by(reference=reference).one()
            current_application = session.query(Application).filter_by(id=application.id).one()
            current_attempt.status = SubmissionAttemptStatus.succeeded.value
            current_application.automation_state = ApplicationAutomationState.confirmed.value
            current_application.status = ApplicationStatus.applied
            session.commit()
        finally:
            session.close()
        raise RuntimeError("post-commit failure")

    monkeypatch.setattr(jt5_task, "_profile_dict", fail_after_confirmed_commit)
    result = execute_reserved_application.run(application.id, reference)
    assert result["success"] is False

    db_session.expire_all()
    saved_application = db_session.query(Application).filter_by(id=application.id).one()
    saved_attempt = db_session.query(SubmissionAttempt).filter_by(reference=reference).one()
    assert saved_application.automation_state == ApplicationAutomationState.confirmed.value
    assert saved_application.status == ApplicationStatus.applied
    assert saved_attempt.status == SubmissionAttemptStatus.succeeded.value
