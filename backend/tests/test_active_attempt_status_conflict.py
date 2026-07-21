from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job, JobStatus
from app.models.user import User


def test_terminal_status_cannot_race_active_application_attempt(auth_client, db_session):
    user = db_session.query(User).filter(User.email == "test@example.com").one()
    job = Job(
        title="Active Attempt Role",
        company="Active Attempt Company",
        url="https://example.com/apply/active",
        status=JobStatus.applied,
        relevance_score=0.9,
    )
    db_session.add(job)
    db_session.flush()

    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applying,
        automation_state=ApplicationAutomationState.applying.value,
        submission_idempotency_key=f"active-attempt-{user.id}-{job.id}",
    )
    db_session.add(application)
    db_session.commit()

    response = auth_client.patch(
        f"/api/applications/{application.id}",
        json={"status": "applied"},
    )

    assert response.status_code == 409, response.text
    assert "active application attempt" in response.json()["detail"].lower()

    db_session.expire_all()
    unchanged = db_session.query(Application).filter(
        Application.id == application.id
    ).one()
    assert unchanged.status == ApplicationStatus.applying
    assert unchanged.automation_state == ApplicationAutomationState.applying.value
