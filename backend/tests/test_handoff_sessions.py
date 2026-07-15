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
from app.models.handoff import HandoffSessionStatus
from app.models.job import Job
from app.models.user import User
from app.services.handoff_session import (
    HandoffSessionConflict,
    HandoffSessionExpired,
    HandoffTokenInvalid,
    begin_handoff_resume,
    claim_handoff_session,
    complete_handoff_resume,
    decrypt_handoff_secret,
    heartbeat_handoff_session,
    issue_handoff_session,
    mark_handoff_ready,
)
from conftest import TestingSessionLocal


def make_records(reason=ManualReviewReason.captcha_detected.value):
    db = TestingSessionLocal()
    user = User(
        email="handoff@example.com",
        hashed_password="not-used",
        full_name="Handoff Tester",
    )
    job = Job(title="Test Role", company="Test Company", url="https://example.test/job")
    db.add_all([user, job])
    db.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
        automation_state=ApplicationAutomationState.needs_review.value,
        submission_idempotency_key=f"handoff-test-{user.id}-{job.id}",
    )
    db.add(application)
    db.flush()
    review = ManualReviewTask(
        application_id=application.id,
        reason_code=reason,
        status=ManualReviewStatus.open.value,
        summary="Human verification required.",
        blocking_url=job.url,
    )
    db.add(review)
    db.commit()
    return db, user, job, application, review


def test_issue_is_idempotent_and_never_uses_legacy_plaintext_token():
    db, _, _, application, review = make_records()
    try:
        first = issue_handoff_session(
            db,
            application,
            review,
            browser_provider="local_cdp",
            browser_endpoint="http://127.0.0.1:9222",
            browser_node_id="node-a",
            current_url=review.blocking_url,
            metadata={"dry_run": True},
        )
        db.commit()
        second = issue_handoff_session(
            db,
            application,
            review,
            browser_provider="local_cdp",
        )

        assert second.session.id == first.session.id
        assert second.resume_token == first.resume_token
        assert first.session.resume_token_hash != first.resume_token
        assert first.session.encrypted_resume_token != first.resume_token
        assert decrypt_handoff_secret(first.session.encrypted_browser_endpoint) == "http://127.0.0.1:9222"
        assert review.resume_token is None
        assert review.status == ManualReviewStatus.in_progress.value
        assert first.session.events[0].event_type == "handoff_issued"
    finally:
        db.close()


def test_claim_consumes_resume_token_and_issues_short_lived_lease():
    db, user, _, application, review = make_records()
    try:
        issued = issue_handoff_session(db, application, review, browser_provider="local_cdp")
        db.commit()
        claimed = claim_handoff_session(
            db,
            issued.session,
            user_id=user.id,
            resume_token=issued.resume_token,
        )
        db.commit()

        assert issued.session.status == HandoffSessionStatus.claimed.value
        assert issued.session.resume_token_consumed_at is not None
        assert issued.session.lease_token_hash != claimed.lease_token
        assert issued.session.lease_expires_at <= issued.session.expires_at
        assert issued.session.events[-1].event_type == "handoff_claimed"

        with pytest.raises(HandoffSessionConflict):
            claim_handoff_session(
                db,
                issued.session,
                user_id=user.id,
                resume_token=issued.resume_token,
            )
    finally:
        db.close()


def test_invalid_token_and_wrong_owner_are_rejected():
    db, user, _, application, review = make_records()
    try:
        issued = issue_handoff_session(db, application, review, browser_provider="local_cdp")
        db.commit()
        with pytest.raises(HandoffTokenInvalid):
            claim_handoff_session(
                db,
                issued.session,
                user_id=user.id,
                resume_token="x" * 32,
            )
        with pytest.raises(HandoffTokenInvalid):
            claim_handoff_session(
                db,
                issued.session,
                user_id=user.id + 999,
                resume_token=issued.resume_token,
            )
    finally:
        db.close()


def test_heartbeat_ready_and_resume_state_machine_is_retry_safe():
    db, user, _, application, review = make_records(ManualReviewReason.mfa_required.value)
    try:
        issued = issue_handoff_session(db, application, review, browser_provider="local_cdp")
        claimed = claim_handoff_session(
            db,
            issued.session,
            user_id=user.id,
            resume_token=issued.resume_token,
        )
        before = issued.session.lease_expires_at
        heartbeat_handoff_session(
            db,
            issued.session,
            user_id=user.id,
            lease_token=claimed.lease_token,
        )
        assert issued.session.lease_expires_at >= before

        with pytest.raises(HandoffSessionConflict):
            mark_handoff_ready(
                db,
                issued.session,
                user_id=user.id,
                lease_token=claimed.lease_token,
                verification={"challenge_cleared": False},
            )

        mark_handoff_ready(
            db,
            issued.session,
            user_id=user.id,
            lease_token=claimed.lease_token,
            verification={
                "challenge_cleared": True,
                "verification_method": "browser_state",
                "code": "must-not-be-persisted",
            },
        )
        assert issued.session.status == HandoffSessionStatus.ready_to_resume.value
        assert issued.session.lease_token_hash is None
        assert "code" not in issued.session.events[-1].payload

        begin_handoff_resume(db, issued.session)
        begin_handoff_resume(db, issued.session)
        assert issued.session.resume_attempt_count == 1
        complete_handoff_resume(db, issued.session, result={"ready_to_submit": True})
        complete_handoff_resume(db, issued.session, result={"ready_to_submit": True})
        assert issued.session.status == HandoffSessionStatus.completed.value
    finally:
        db.close()


def test_expired_session_cannot_be_claimed():
    db, user, _, application, review = make_records()
    try:
        issued = issue_handoff_session(db, application, review, browser_provider="local_cdp")
        issued.session.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HandoffSessionExpired):
            claim_handoff_session(
                db,
                issued.session,
                user_id=user.id,
                resume_token=issued.resume_token,
            )
        assert issued.session.status == HandoffSessionStatus.expired.value
    finally:
        db.close()


def test_non_resumable_review_reason_is_rejected():
    db, _, _, application, review = make_records(ManualReviewReason.ambiguous_question.value)
    try:
        with pytest.raises(ValueError):
            issue_handoff_session(db, application, review, browser_provider="local_cdp")
    finally:
        db.close()
