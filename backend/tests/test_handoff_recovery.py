from datetime import datetime, timedelta

import pytest

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import HandoffSessionEvent, HandoffSessionStatus
from app.models.job import Job
from app.models.user import User
from app.services.handoff_recovery import recover_handoff_lease
from app.services.handoff_session import (
    HandoffSessionConflict,
    HandoffSessionExpired,
    HandoffTokenInvalid,
    claim_handoff_session,
    issue_handoff_session,
)


def _claimed_session(db_session):
    user = User(
        email="recovery@example.com",
        hashed_password="not-used",
        full_name="Recovery Tester",
    )
    job = Job(
        title="Recovery Role",
        company="Recovery Company",
        url="https://example.test/recovery",
    )
    db_session.add_all([user, job])
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.needs_review.value,
        submission_idempotency_key=f"recovery-{user.id}-{job.id}",
    )
    db_session.add(application)
    db_session.flush()
    review = ManualReviewTask(
        application_id=application.id,
        reason_code=ManualReviewReason.captcha_detected.value,
        status=ManualReviewStatus.open.value,
        summary="Human verification required.",
        blocking_url=job.url,
    )
    db_session.add(review)
    db_session.flush()
    issued = issue_handoff_session(
        db_session,
        application,
        review,
        browser_provider="local_cdp",
        current_url=job.url,
    )
    claimed = claim_handoff_session(
        db_session,
        issued.session,
        user_id=user.id,
        resume_token=issued.resume_token,
    )
    db_session.flush()
    return user, application, issued.session, claimed.lease_token


def test_expired_lease_can_be_rotated_without_duplicate_application(db_session):
    user, application, session, first_lease = _claimed_session(db_session)
    first_hash = session.lease_token_hash
    session.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)

    recovered = recover_handoff_lease(
        db_session,
        session,
        user_id=user.id,
    )
    db_session.flush()

    assert recovered.lease_token != first_lease
    assert session.lease_token_hash != first_hash
    assert session.status == HandoffSessionStatus.claimed.value
    assert session.lease_recovery_count == 1
    assert session.lease_expires_at > datetime.utcnow()
    assert db_session.query(Application).filter(Application.id == application.id).count() == 1
    assert db_session.query(Application).filter(
        Application.submission_idempotency_key == application.submission_idempotency_key,
    ).count() == 1

    event = (
        db_session.query(HandoffSessionEvent)
        .filter(
            HandoffSessionEvent.handoff_session_id == session.id,
            HandoffSessionEvent.event_type == "handoff_lease_recovered",
        )
        .one()
    )
    assert event.payload["recovery_count"] == 1
    assert "lease_token" not in str(event.payload)


def test_active_lease_cannot_be_displaced(db_session):
    user, _, session, _ = _claimed_session(db_session)

    with pytest.raises(HandoffSessionConflict):
        recover_handoff_lease(
            db_session,
            session,
            user_id=user.id,
        )

    assert session.lease_recovery_count == 0


def test_recovery_is_owner_scoped(db_session):
    user, _, session, _ = _claimed_session(db_session)
    session.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)

    with pytest.raises(HandoffTokenInvalid):
        recover_handoff_lease(
            db_session,
            session,
            user_id=user.id + 999,
        )

    assert session.lease_recovery_count == 0


def test_expired_handoff_fails_closed_during_recovery(db_session):
    user, _, session, _ = _claimed_session(db_session)
    session.expires_at = datetime.utcnow() - timedelta(seconds=1)
    session.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)

    with pytest.raises(HandoffSessionExpired):
        recover_handoff_lease(
            db_session,
            session,
            user_id=user.id,
        )

    assert session.status == HandoffSessionStatus.expired.value
    assert session.failure_reason
    assert session.lease_recovery_count == 0
