from datetime import datetime, timedelta

from app.celery_app import celery_app
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewReason,
    ManualReviewTask,
)
from app.models.job import Job
from app.models.notification import Notification
from app.models.user import User
from app.services.application_recovery import (
    RECOVERY_KIND,
    recover_stale_application_attempt,
    recover_stale_application_attempts,
)
from app.services.operations_settings import get_operations_settings


def _make_application(
    db_session,
    *,
    suffix: str,
    now: datetime,
    age_minutes: int,
    dry_run: bool | None,
):
    user = User(
        email=f"recovery-{suffix}@example.test",
        hashed_password="test-hash",
        full_name="Recovery Test",
    )
    job = Job(
        external_id=f"recovery-job-{suffix}",
        title=f"Recovery Job {suffix}",
        company="Recovery Employer",
        url=f"https://job-boards.greenhouse.io/recovery/jobs/{suffix}",
    )
    db_session.add_all([user, job])
    db_session.flush()
    started_at = now - timedelta(minutes=age_minutes)
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applying,
        automation_state=ApplicationAutomationState.applying.value,
        submission_attempt_count=1,
        last_submission_attempt_at=started_at,
        submission_idempotency_key=f"recovery:{suffix}",
        created_at=started_at,
    )
    db_session.add(application)
    db_session.flush()
    if dry_run is not None:
        db_session.add(ApplicationEvent(
            application_id=application.id,
            event_type="application_attempt_started",
            from_state=ApplicationAutomationState.ready_to_apply.value,
            to_state=ApplicationAutomationState.applying.value,
            payload={"dry_run": dry_run, "attempt": 1},
            created_at=started_at,
        ))
    db_session.commit()
    db_session.refresh(application)
    return application


def test_stale_dry_run_moves_to_manual_review(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    application = _make_application(
        db_session,
        suffix="dry",
        now=now,
        age_minutes=45,
        dry_run=True,
    )

    result = recover_stale_application_attempt(
        db_session,
        application,
        now=now,
        timeout_minutes=30,
    )
    db_session.commit()
    db_session.refresh(application)

    assert result["recovered"] is True
    assert result["dry_run"] is True
    assert result["reason_code"] == ManualReviewReason.automation_error.value
    assert application.status == ApplicationStatus.pending
    assert application.automation_state == ApplicationAutomationState.needs_review.value

    review = db_session.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
    ).one()
    assert review.reason_code == ManualReviewReason.automation_error.value
    assert (review.details or {})["kind"] == RECOVERY_KIND
    assert result["review_id"] == review.id

    notification = db_session.query(Notification).filter(
        Notification.user_id == application.user_id,
    ).one()
    assert (notification.data or {})["kind"] == RECOVERY_KIND
    assert (notification.data or {})["review_id"] == review.id

    recovery_event = db_session.query(ApplicationEvent).filter(
        ApplicationEvent.application_id == application.id,
        ApplicationEvent.event_type == "stale_application_attempt_recovered",
    ).one()
    assert recovery_event.from_state == ApplicationAutomationState.applying.value
    assert recovery_event.to_state == ApplicationAutomationState.needs_review.value

    repeated = recover_stale_application_attempt(
        db_session,
        application,
        now=now + timedelta(minutes=5),
        timeout_minutes=30,
    )
    db_session.commit()
    assert repeated["recovered"] is False
    assert repeated["reason"] == "not_applying"
    assert db_session.query(Notification).filter(
        Notification.user_id == application.user_id,
    ).count() == 1


def test_stale_live_attempt_becomes_submission_uncertain(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    application = _make_application(
        db_session,
        suffix="live",
        now=now,
        age_minutes=60,
        dry_run=False,
    )

    result = recover_stale_application_attempt(
        db_session,
        application,
        now=now,
        timeout_minutes=30,
    )
    db_session.commit()
    db_session.refresh(application)

    assert result["recovered"] is True
    assert result["dry_run"] is False
    assert result["reason_code"] == ManualReviewReason.submission_confirmation_uncertain.value
    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value
    review = db_session.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
    ).one()
    assert review.reason_code == ManualReviewReason.submission_confirmation_uncertain.value


def test_unknown_attempt_mode_fails_closed_to_submission_uncertain(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    application = _make_application(
        db_session,
        suffix="unknown",
        now=now,
        age_minutes=60,
        dry_run=None,
    )

    result = recover_stale_application_attempt(
        db_session,
        application,
        now=now,
        timeout_minutes=30,
    )
    db_session.commit()
    db_session.refresh(application)

    assert result["recovered"] is True
    assert result["dry_run"] is None
    assert application.automation_state == ApplicationAutomationState.submission_uncertain.value


def test_fresh_attempt_is_not_recovered(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    application = _make_application(
        db_session,
        suffix="fresh",
        now=now,
        age_minutes=5,
        dry_run=True,
    )

    result = recover_stale_application_attempt(
        db_session,
        application,
        now=now,
        timeout_minutes=30,
    )
    db_session.commit()
    db_session.refresh(application)

    assert result["recovered"] is False
    assert result["reason"] == "attempt_still_fresh"
    assert application.automation_state == ApplicationAutomationState.applying.value
    assert db_session.query(ManualReviewTask).filter(
        ManualReviewTask.application_id == application.id,
    ).count() == 0


def test_batch_recovery_only_selects_stale_rows(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    _make_application(
        db_session,
        suffix="batch-stale",
        now=now,
        age_minutes=45,
        dry_run=True,
    )
    _make_application(
        db_session,
        suffix="batch-fresh",
        now=now,
        age_minutes=10,
        dry_run=True,
    )

    result = recover_stale_application_attempts(
        db_session,
        now=now,
        timeout_minutes=30,
    )
    db_session.commit()

    assert result["checked"] == 1
    assert result["recovered"] == 1
    assert result["dry_run_recovered"] == 1
    assert result["uncertain_recovered"] == 0


def test_stale_attempt_timeout_is_configurable(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_STALE_ATTEMPT_MINUTES", "45")
    get_operations_settings.cache_clear()
    try:
        assert get_operations_settings().stale_attempt_minutes == 45
    finally:
        get_operations_settings.cache_clear()


def test_stale_recovery_task_runs_every_fifteen_minutes():
    schedule = celery_app.conf.beat_schedule["recover-stale-application-attempts"]
    assert schedule["task"] == "app.tasks.operations.recover_stale_application_attempts"
    rendered = str(schedule["schedule"])
    assert "5" in rendered
    assert "20" in rendered
    assert "35" in rendered
    assert "50" in rendered
