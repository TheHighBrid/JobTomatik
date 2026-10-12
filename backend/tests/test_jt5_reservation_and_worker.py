"""JT5 reservation concurrency and worker outcome integration tests."""
from concurrent.futures import ThreadPoolExecutor
import time
from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError

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

    def claim_once():
        for retry in range(2):
            session = TestingSessionLocal()
            try:
                claimed = claim_jt5_attempt(session, application.id, reference)
                session.commit()
                return claimed is not None
            except OperationalError:
                session.rollback()
                if retry == 0:
                    time.sleep(0.05)
                    continue
                raise
            finally:
                session.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim_once(), range(2)))

    assert sum(1 for owned in results if owned) == 1


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
    monkeypatch.setattr(
        "app.tasks.jt5_execution._record_result_evidence",
        lambda *args, **kwargs: None,
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
    from app.tasks.jt5_execution import execute_reserved_application

    user = db_session.query(User).filter(User.email == "test@example.com").one()
    application = _application(db_session, user, _job(db_session))
    db_session.commit()

    def ambiguous_publish(*args, **kwargs):
        raise ConnectionError("broker acknowledgement lost")

    monkeypatch.setattr(execute_reserved_application, "apply_async", ambiguous_publish)
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
