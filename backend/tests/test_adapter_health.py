from datetime import datetime, timedelta

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ManualReviewReason,
    ManualReviewTask,
)
from app.models.job import Job
from app.models.user import User
from app.services.adapter_health import build_adapter_health_report


def _user(db_session, email: str) -> User:
    user = User(email=email, hashed_password="test-hash", full_name="Health Test")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _application(
    db_session,
    user: User,
    *,
    index: int,
    url: str,
    state: str,
    attempted_at: datetime,
) -> Application:
    job = Job(
        external_id=f"health-job-{index}",
        title=f"Health Job {index}",
        company=f"Health Employer {index}",
        url=url,
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        automation_state=state,
        submission_attempt_count=1,
        last_submission_attempt_at=attempted_at,
        submission_idempotency_key=f"health:{user.id}:{index}",
        created_at=attempted_at,
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)
    return application


def test_adapter_health_reports_metrics_and_actionable_alerts(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    user = _user(db_session, "adapter-health@example.test")

    failed = _application(
        db_session,
        user,
        index=1,
        url="https://job-boards.greenhouse.io/example/jobs/123",
        state=ApplicationAutomationState.failed.value,
        attempted_at=now - timedelta(minutes=20),
    )
    _application(
        db_session,
        user,
        index=2,
        url="https://job-boards.greenhouse.io/example/jobs/456",
        state=ApplicationAutomationState.confirmed.value,
        attempted_at=now - timedelta(minutes=10),
    )
    login_review = _application(
        db_session,
        user,
        index=3,
        url="https://example.wd5.myworkdayjobs.com/jobs/job/R-1",
        state=ApplicationAutomationState.needs_review.value,
        attempted_at=now - timedelta(minutes=5),
    )

    for offset in (18, 17):
        db_session.add(ManualReviewTask(
            application_id=failed.id,
            reason_code=ManualReviewReason.validation_error.value,
            summary="Synthetic validation failure",
            created_at=now - timedelta(minutes=offset),
        ))
    for offset in (4, 3):
        db_session.add(ManualReviewTask(
            application_id=login_review.id,
            reason_code=ManualReviewReason.login_required.value,
            summary="Synthetic login handoff",
            created_at=now - timedelta(minutes=offset),
        ))
    db_session.commit()

    report = build_adapter_health_report(
        db_session,
        user.id,
        window_hours=24,
        failure_threshold=2,
        now=now,
    )

    assert report["summary"]["attempts"] == 3
    assert report["summary"]["successful"] == 1
    assert report["summary"]["confirmed"] == 1
    assert report["summary"]["manual_review"] == 1
    assert report["summary"]["failed"] == 1
    assert report["summary"]["status"] == "critical"

    platforms = {item["platform"]: item for item in report["platforms"]}
    assert platforms["greenhouse"]["status"] == "degraded"
    assert platforms["greenhouse"]["success_rate"] == 0.5
    assert platforms["greenhouse"]["reason_counts"]["validation_error"] == 2
    assert platforms["workday"]["status"] == "critical"
    assert platforms["workday"]["reason_counts"]["login_required"] == 2

    alert_codes = {item["code"] for item in report["alerts"]}
    assert "validation_failure_spike" in alert_codes
    assert "login_lockout_risk" in alert_codes


def test_adapter_health_ignores_attempts_outside_window(db_session):
    now = datetime.utcnow().replace(microsecond=0)
    user = _user(db_session, "stale-health@example.test")
    _application(
        db_session,
        user,
        index=10,
        url="https://job-boards.greenhouse.io/example/jobs/789",
        state=ApplicationAutomationState.failed.value,
        attempted_at=now - timedelta(hours=48),
    )

    report = build_adapter_health_report(
        db_session,
        user.id,
        window_hours=24,
        failure_threshold=2,
        now=now,
    )

    assert report["summary"]["attempts"] == 0
    assert report["summary"]["status"] == "no_data"
    assert report["platforms"] == []
    assert report["alerts"] == []


def test_adapter_health_endpoint_is_authenticated_and_user_scoped(
    auth_client,
    db_session,
):
    now = datetime.utcnow().replace(microsecond=0)
    current_user = db_session.query(User).filter(
        User.email == "test@example.com"
    ).one()
    other_user = _user(db_session, "other-health@example.test")

    _application(
        db_session,
        current_user,
        index=20,
        url="https://job-boards.greenhouse.io/example/jobs/100",
        state=ApplicationAutomationState.confirmed.value,
        attempted_at=now - timedelta(minutes=2),
    )
    _application(
        db_session,
        other_user,
        index=21,
        url="https://example.wd5.myworkdayjobs.com/jobs/job/R-2",
        state=ApplicationAutomationState.failed.value,
        attempted_at=now - timedelta(minutes=1),
    )

    response = auth_client.get(
        "/api/adapter-health?window_hours=24&failure_threshold=2"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["attempts"] == 1
    assert payload["summary"]["confirmed"] == 1
    assert [item["platform"] for item in payload["platforms"]] == ["greenhouse"]
