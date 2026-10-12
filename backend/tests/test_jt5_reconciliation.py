"""Regression tests for JT5 stale dispatch and crash reconciliation."""
from datetime import datetime, timedelta

from app.models.application import ApplicationAutomationState
from app.models.submission_integrity import SubmissionAttemptStatus
from app.services.application_attempt_jt5 import reserve_jt5_attempt
from app.services.jt5_reconciliation import reconcile_stale_jt5_attempts
from tests.test_jt5_reservation_and_worker import _application, _job, _user


def test_stale_queued_attempt_never_republished(db_session):
    user = _user(db_session, email="jt5-stale-queued@example.com")
    application = _application(db_session, user, _job(db_session))
    _, attempt = reserve_jt5_attempt(
        db_session, application_id=application.id, authenticated_user_id=user.id
    )
    db_session.commit()
    attempt.queued_at = datetime.utcnow() - timedelta(hours=2)
    db_session.commit()

    reconciled = reconcile_stale_jt5_attempts(db_session)
    assert reconciled == [attempt.reference]
    db_session.refresh(attempt)
    assert attempt.status == SubmissionAttemptStatus.uncertain.value
    assert attempt.attempt_metadata["dispatch_status"] == "reconciliation_required"
    assert attempt.attempt_metadata["automatic_retry_allowed"] is False
    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value
    assert reconcile_stale_jt5_attempts(db_session) == []


def test_stale_in_progress_worker_crash_is_uncertain(db_session):
    user = _user(db_session, email="jt5-stale-running@example.com")
    application = _application(db_session, user, _job(db_session))
    _, attempt = reserve_jt5_attempt(
        db_session, application_id=application.id, authenticated_user_id=user.id
    )
    attempt.status = SubmissionAttemptStatus.in_progress.value
    attempt.started_at = datetime.utcnow() - timedelta(hours=2)
    db_session.commit()
    assert reconcile_stale_jt5_attempts(db_session) == [attempt.reference]
    db_session.refresh(attempt)
    assert attempt.status == SubmissionAttemptStatus.uncertain.value
    assert attempt.attempt_metadata["reconciliation_reason"] == "stale_in_progress"


def test_recent_attempt_is_untouched(db_session):
    user = _user(db_session, email="jt5-recent@example.com")
    application = _application(db_session, user, _job(db_session))
    _, attempt = reserve_jt5_attempt(
        db_session, application_id=application.id, authenticated_user_id=user.id
    )
    db_session.commit()
    assert reconcile_stale_jt5_attempts(db_session) == []
    db_session.refresh(attempt)
    assert attempt.status == SubmissionAttemptStatus.queued.value


def test_stale_attempt_not_starved_by_recent_attempt(db_session):
    user = _user(db_session, email="jt5-batch-age@example.com")
    first = _application(db_session, user, _job(db_session))
    _, recent = reserve_jt5_attempt(
        db_session, application_id=first.id, authenticated_user_id=user.id
    )
    db_session.commit()
    second = _application(db_session, user, _job(db_session))
    _, stale = reserve_jt5_attempt(
        db_session, application_id=second.id, authenticated_user_id=user.id
    )
    db_session.commit()
    stale.queued_at = datetime.utcnow() - timedelta(hours=2)
    db_session.commit()
    assert reconcile_stale_jt5_attempts(db_session, limit=1) == [stale.reference]
    db_session.refresh(recent)
    assert recent.status == SubmissionAttemptStatus.queued.value
