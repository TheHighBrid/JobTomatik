from datetime import datetime, timedelta

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.handoff import HandoffChallengeType, HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval, SubmissionApprovalStatus
from app.models.user import User
from app.services.application_recovery import recover_stale_application_attempt


OPERATOR_SOURCE = "authenticated_user_operator_assisted"


def _make_operator_final_submit_window(db_session, *, now: datetime):
    user = User(
        email="operator-recovery@example.test",
        hashed_password="test-hash",
        full_name="Operator Recovery",
    )
    job = Job(
        external_id="operator-recovery-job",
        title="Risk Analyst",
        company="Recovery Lever",
        url="https://jobs.lever.co/recovery/posting-123/apply",
    )
    db_session.add_all([user, job])
    db_session.flush()

    started_at = now - timedelta(minutes=60)
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applying,
        automation_state=ApplicationAutomationState.applying.value,
        submission_attempt_count=2,
        last_submission_attempt_at=started_at,
        submission_idempotency_key="operator-recovery-idempotency",
        created_at=started_at,
    )
    db_session.add(application)
    db_session.flush()

    # Preparation really was a dry run. Recovery must stop trusting this historical
    # bit once the owner has consumed the exact final-submit approval.
    db_session.add(ApplicationEvent(
        application_id=application.id,
        event_type="application_attempt_started",
        from_state=ApplicationAutomationState.ready_to_apply.value,
        to_state=ApplicationAutomationState.applying.value,
        payload={"dry_run": True, "attempt": 1},
        created_at=started_at,
    ))

    review = ManualReviewTask(
        application_id=application.id,
        reason_code=ManualReviewReason.operator_final_submit_required.value,
        status=ManualReviewStatus.in_progress.value,
        summary="Owner final action required.",
        blocking_url=job.url,
    )
    db_session.add(review)
    db_session.flush()

    handoff = ManualHandoffSession(
        application_id=application.id,
        manual_review_id=review.id,
        user_id=user.id,
        challenge_type=HandoffChallengeType.final_submit.value,
        status=HandoffSessionStatus.awaiting_user.value,
        idempotency_key=f"handoff:{application.id}:operator-final",
        resume_token_hash="hash",
        encrypted_resume_token="encrypted",
        resume_token_prefix="prefix",
        browser_provider="local_cdp",
        current_url=job.url,
        current_fingerprint="fingerprint",
        expires_at=now + timedelta(minutes=20),
        handoff_metadata={"adapter": "lever", "adapter_version": "1.1.0"},
    )
    db_session.add(handoff)
    db_session.flush()

    digest = "a" * 64
    approval = SubmissionApproval(
        application_id=application.id,
        user_id=user.id,
        platform="lever",
        status=SubmissionApprovalStatus.consumed.value,
        employer=job.company,
        role=job.title,
        application_url=job.url,
        submission_idempotency_key=application.submission_idempotency_key,
        profile_snapshot_hash=digest,
        resume_hash=digest,
        cover_letter_hash=digest,
        answer_payload_hash=digest,
        combined_payload_hash=digest,
        approved_at=started_at,
        expires_at=now + timedelta(minutes=20),
        consumed_at=started_at,
        approval_metadata={
            "approval_source": OPERATOR_SOURCE,
            "handoff_public_id": handoff.public_id,
            "operator_final_click_required": True,
            "automated_submission_authorized": False,
            "queue_submission_authorized": False,
            "automatic_retry_allowed": False,
        },
    )
    db_session.add(approval)
    db_session.commit()
    db_session.refresh(application)
    db_session.refresh(handoff)
    db_session.refresh(approval)
    return application, handoff, approval


def test_periodic_stale_recovery_does_not_steal_active_operator_final_submit_window(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    application, handoff, approval = _make_operator_final_submit_window(db_session, now=now)

    result = recover_stale_application_attempt(
        db_session,
        application,
        now=now,
        timeout_minutes=30,
    )
    db_session.commit()
    db_session.refresh(application)

    assert result["recovered"] is False
    assert result["reason"] == "operator_final_submit_handoff_active"
    assert result["handoff_public_id"] == handoff.public_id
    assert result["approval_reference"] == approval.reference
    assert result["automatic_retry_allowed"] is False
    assert application.automation_state == ApplicationAutomationState.applying.value
    assert db_session.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
        ManualReviewTask.reason_code == ManualReviewReason.submission_confirmation_uncertain.value,
    ).count() == 0


def test_runtime_interruption_quarantines_operator_window_even_with_historical_dry_run(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    application, handoff, approval = _make_operator_final_submit_window(db_session, now=now)

    result = recover_stale_application_attempt(
        db_session,
        application,
        now=now,
        force_interrupted=True,
    )
    db_session.commit()
    db_session.refresh(application)

    assert result["recovered"] is True
    assert result["dry_run"] is None
    assert result["runtime_interrupted"] is True
    assert result["automatic_retry_allowed"] is False
    assert result["operator_final_submit_checkpoint"]["handoff_public_id"] == handoff.public_id
    assert result["operator_final_submit_checkpoint"]["approval_reference"] == approval.reference
    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value

    uncertain_review = db_session.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
        ManualReviewTask.reason_code == ManualReviewReason.submission_confirmation_uncertain.value,
    ).one()
    assert (uncertain_review.details or {})["dry_run"] is None
    assert (uncertain_review.details or {})["automatic_retry_allowed"] is False
