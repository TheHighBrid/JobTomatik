from datetime import datetime, timedelta, timezone

from tests.conftest import TestingSessionLocal

from app.models.application import Application, ApplicationStatus, FollowUp
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User


def _current_user(db):
    return db.query(User).filter(User.email == "test@example.com").one()


def test_operations_agenda_preserves_uncertain_and_sending_delivery_semantics(auth_client):
    db = TestingSessionLocal()
    try:
        user = _current_user(db)
        job = Job(
            title="Platform Engineer",
            company="DeliveryCo",
            external_id="operations-delivery-states",
            source=JobSource.manual,
            status=JobStatus.approved,
        )
        db.add(job)
        db.flush()
        application = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.applied,
            applied_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        db.add(application)
        db.flush()
        db.add_all(
            [
                FollowUp(
                    application_id=application.id,
                    scheduled_at=datetime.now(timezone.utc) - timedelta(hours=1),
                    subject="Uncertain follow-up",
                    message="Exact message",
                    recipient_email="recruiter@delivery.example",
                    status="delivery_uncertain",
                    approval_status="consumed",
                ),
                FollowUp(
                    application_id=application.id,
                    scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=20),
                    subject="Sending follow-up",
                    message="Exact message",
                    recipient_email="recruiter@delivery.example",
                    status="sending",
                    approval_status="active",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = auth_client.get("/api/operations/workspace?agenda_days=1")
    assert response.status_code == 200
    followups = [
        item
        for item in response.json()["agenda"]
        if item["status"] in {"delivery_uncertain", "sending"}
    ]
    assert len(followups) == 2

    uncertain = next(item for item in followups if item["status"] == "delivery_uncertain")
    assert uncertain["item_type"] == "followup_delivery"
    assert uncertain["priority"] == "high"
    assert uncertain["title"] == "Follow-up delivery uncertain"

    sending = next(item for item in followups if item["status"] == "sending")
    assert sending["item_type"] == "followup_delivery"
    assert sending["title"] == "Follow-up delivery in progress"
