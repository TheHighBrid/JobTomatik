from datetime import datetime, timedelta

from app.celery_app import celery_app
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ManualReviewReason,
    ManualReviewTask,
)
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.user import User
from app.services.adapter_health_notifications import (
    NOTIFICATION_KIND,
    sync_adapter_health_notifications,
)


def _user(db_session, email="health-alerts@example.test"):
    user = User(email=email, hashed_password="test-hash", full_name="Health Alerts")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _failed_application(db_session, user, now):
    job = Job(
        external_id="health-alert-job",
        title="Adapter Health Test",
        company="Example Employer",
        url="https://job-boards.greenhouse.io/example/jobs/123",
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        automation_state=ApplicationAutomationState.failed.value,
        submission_attempt_count=1,
        last_submission_attempt_at=now - timedelta(minutes=5),
        submission_idempotency_key=f"health-alert:{user.id}",
        created_at=now - timedelta(minutes=5),
    )
    db_session.add(application)
    db_session.flush()
    for offset in (4, 3):
        db_session.add(ManualReviewTask(
            application_id=application.id,
            reason_code=ManualReviewReason.validation_error.value,
            summary="Synthetic validation failure",
            created_at=now - timedelta(minutes=offset),
        ))
    db_session.commit()
    db_session.refresh(application)
    return application


def test_health_alert_notifications_are_created_and_deduplicated(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    user = _user(db_session)
    _failed_application(db_session, user, now)

    first = sync_adapter_health_notifications(
        db_session,
        user.id,
        failure_threshold=2,
        now=now,
    )
    db_session.commit()

    notifications = db_session.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.type == NotificationType.system,
    ).all()
    assert first["alerts_detected"] >= 1
    assert first["notifications_created"] == first["alerts_detected"]
    assert first["notifications_deduplicated"] == 0
    assert len(notifications) == first["notifications_created"]
    assert all((item.data or {}).get("kind") == NOTIFICATION_KIND for item in notifications)
    assert any((item.data or {}).get("code") == "validation_failure_spike" for item in notifications)

    second = sync_adapter_health_notifications(
        db_session,
        user.id,
        failure_threshold=2,
        now=now + timedelta(minutes=10),
    )
    db_session.commit()

    assert second["notifications_created"] == 0
    assert second["notifications_deduplicated"] == second["alerts_detected"]
    assert db_session.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.type == NotificationType.system,
    ).count() == len(notifications)


def test_health_alert_notifications_are_user_scoped(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    first_user = _user(db_session, "first-health-alert@example.test")
    second_user = _user(db_session, "second-health-alert@example.test")
    _failed_application(db_session, first_user, now)

    result = sync_adapter_health_notifications(
        db_session,
        second_user.id,
        failure_threshold=2,
        now=now,
    )
    db_session.commit()

    assert result["alerts_detected"] == 0
    assert result["notifications_created"] == 0
    assert db_session.query(Notification).filter(
        Notification.user_id == second_user.id,
    ).count() == 0


def test_adapter_health_alert_task_is_registered_hourly():
    schedule = celery_app.conf.beat_schedule["refresh-adapter-health-alerts-hourly"]
    assert schedule["task"] == "app.tasks.operations.refresh_adapter_health_alerts"
    assert "15" in str(schedule["schedule"])
