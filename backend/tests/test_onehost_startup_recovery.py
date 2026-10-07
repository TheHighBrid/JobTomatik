"""Regression coverage for fail-closed OneHost worker restart recovery."""

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
from app.models.handoff import HandoffSessionStatus, ManualHandoffSession
from app.models.job import Job
from app.models.user import User
from app.services.onehost_startup_recovery import reconcile_onehost_worker_restart


def _application(db, suffix: str, *, dry_run: bool | None, state: str):
    user = User(
        email=f"onehost-restart-{suffix}@example.test",
        hashed_password="test",
        full_name="OneHost Restart Test",
    )
    job = Job(
        external_id=f"onehost-restart-{suffix}",
        title="Synthetic Role",
        company="Synthetic Employer",
        url=f"https://job-boards.greenhouse.io/example/jobs/{suffix}",
    )
    db.add_all([user, job])
    db.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=(
            ApplicationStatus.applying
            if state == ApplicationAutomationState.applying.value
            else ApplicationStatus.pending
        ),
        automation_state=state,
        submission_idempotency_key=f"onehost-restart:{suffix}",
        submission_attempt_count=1 if state == ApplicationAutomationState.applying.value else 0,
        last_submission_attempt_at=(
            datetime.utcnow()
            if state == ApplicationAutomationState.applying.value
            else None
        ),
    )
    db.add(application)
    db.flush()
    if state == ApplicationAutomationState.applying.value and dry_run is not None:
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="application_attempt_started",
                from_state=ApplicationAutomationState.ready_to_apply.value,
                to_state=ApplicationAutomationState.applying.value,
                payload={"dry_run": dry_run, "attempt": 1},
            )
        )
    return user, application


def _handoff(db, user, application, suffix: str, status: str):
    review = ManualReviewTask(
        application_id=application.id,
        reason_code=ManualReviewReason.captcha_detected.value,
        status=ManualReviewStatus.in_progress.value,
        summary="Synthetic restart handoff",
    )
    db.add(review)
    db.flush()
    session = ManualHandoffSession(
        public_id=f"00000000-0000-4000-8000-{int(suffix):012d}",
        application_id=application.id,
        manual_review_id=review.id,
        user_id=user.id,
        challenge_type="captcha",
        status=status,
        idempotency_key=f"handoff:restart:{suffix}",
        resume_token_hash="a" * 64,
        encrypted_resume_token="synthetic",
        resume_token_prefix="synthetic",
        browser_provider="local",
        expires_at=datetime.utcnow() + timedelta(hours=1),
        handoff_metadata={},
    )
    db.add(session)
    db.flush()
    return session


def test_worker_restart_fails_resuming_handoff_and_live_application_uncertain(db_session):
    user, application = _application(
        db_session,
        "1",
        dry_run=False,
        state=ApplicationAutomationState.applying.value,
    )
    session = _handoff(
        db_session,
        user,
        application,
        "1",
        HandoffSessionStatus.resuming.value,
    )
    db_session.commit()

    result = reconcile_onehost_worker_restart(db_session)
    db_session.commit()
    db_session.refresh(application)
    db_session.refresh(session)

    assert result["resuming_handoffs_failed"] == 1
    assert result["automatic_live_retry_performed"] is False
    assert result["submission_authorized"] is False
    assert session.status == HandoffSessionStatus.failed.value
    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value
    assert application.automation_state not in {
        ApplicationAutomationState.submitted.value,
        ApplicationAutomationState.confirmed.value,
    }

    repeated = reconcile_onehost_worker_restart(db_session)
    db_session.commit()
    assert repeated["resuming_handoffs_failed"] == 0
    assert repeated["application_recovery"]["recovered"] == 0


def test_worker_restart_recovers_proven_dry_run_without_live_retry(db_session):
    _, application = _application(
        db_session,
        "2",
        dry_run=True,
        state=ApplicationAutomationState.applying.value,
    )
    db_session.commit()

    result = reconcile_onehost_worker_restart(db_session)
    db_session.commit()
    db_session.refresh(application)

    assert result["application_recovery"]["dry_run_recovered"] == 1
    assert application.automation_state == ApplicationAutomationState.ready_to_apply.value
    assert result["automatic_live_retry_performed"] is False


def test_worker_restart_preserves_user_owned_pre_resume_handoff(db_session):
    user, application = _application(
        db_session,
        "3",
        dry_run=None,
        state=ApplicationAutomationState.needs_review.value,
    )
    session = _handoff(
        db_session,
        user,
        application,
        "3",
        HandoffSessionStatus.claimed.value,
    )
    db_session.commit()

    result = reconcile_onehost_worker_restart(db_session)
    db_session.commit()
    db_session.refresh(session)
    db_session.refresh(application)

    assert result["resuming_handoffs_checked"] == 0
    assert session.status == HandoffSessionStatus.claimed.value
    assert application.automation_state == ApplicationAutomationState.needs_review.value


def test_repeated_worker_restart_reconciliation_is_idempotent_and_fail_closed(db_session):
    live_user, live_application = _application(
        db_session,
        "41",
        dry_run=False,
        state=ApplicationAutomationState.applying.value,
    )
    _, dry_application = _application(
        db_session,
        "42",
        dry_run=True,
        state=ApplicationAutomationState.applying.value,
    )
    claimed_user, claimed_application = _application(
        db_session,
        "43",
        dry_run=None,
        state=ApplicationAutomationState.needs_review.value,
    )
    resuming_user, resuming_application = _application(
        db_session,
        "44",
        dry_run=None,
        state=ApplicationAutomationState.needs_review.value,
    )
    claimed_session = _handoff(
        db_session,
        claimed_user,
        claimed_application,
        "43",
        HandoffSessionStatus.claimed.value,
    )
    resuming_session = _handoff(
        db_session,
        resuming_user,
        resuming_application,
        "44",
        HandoffSessionStatus.resuming.value,
    )
    db_session.commit()

    first = reconcile_onehost_worker_restart(db_session)
    db_session.commit()

    for record in (
        live_application,
        dry_application,
        claimed_application,
        resuming_application,
        claimed_session,
        resuming_session,
    ):
        db_session.refresh(record)

    assert first["resuming_handoffs_failed"] == 1
    assert first["automatic_live_retry_performed"] is False
    assert first["submission_authorized"] is False
    assert live_application.automation_state == ApplicationAutomationState.submission_uncertain.value
    assert dry_application.automation_state == ApplicationAutomationState.ready_to_apply.value
    assert claimed_application.automation_state == ApplicationAutomationState.needs_review.value
    assert resuming_application.automation_state == ApplicationAutomationState.needs_review.value
    assert claimed_session.status == HandoffSessionStatus.claimed.value
    assert resuming_session.status == HandoffSessionStatus.failed.value

    protected_ids = {
        live_application.id,
        dry_application.id,
        claimed_application.id,
        resuming_application.id,
    }
    forbidden_states = {
        ApplicationAutomationState.submitted.value,
        ApplicationAutomationState.confirmed.value,
    }

    for _ in range(25):
        repeated = reconcile_onehost_worker_restart(db_session)
        db_session.commit()
        assert repeated["resuming_handoffs_failed"] == 0
        assert repeated["application_recovery"]["recovered"] == 0
        assert repeated["automatic_live_retry_performed"] is False
        assert repeated["submission_authorized"] is False

        applications = (
            db_session.query(Application)
            .filter(Application.id.in_(protected_ids))
            .all()
        )
        assert len(applications) == 4
        assert all(app.automation_state not in forbidden_states for app in applications)

    db_session.refresh(live_application)
    db_session.refresh(dry_application)
    db_session.refresh(claimed_session)
    db_session.refresh(resuming_session)
    assert live_application.automation_state == ApplicationAutomationState.submission_uncertain.value
    assert dry_application.automation_state == ApplicationAutomationState.ready_to_apply.value
    assert claimed_session.status == HandoffSessionStatus.claimed.value
    assert resuming_session.status == HandoffSessionStatus.failed.value
