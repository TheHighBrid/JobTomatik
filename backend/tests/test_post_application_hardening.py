from app.models.application import Application, ApplicationEvent, ApplicationStatus
from app.models.intelligence import RecruiterContact, RecruiterInteraction
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from tests.conftest import TestingSessionLocal


def _user(db):
    return db.query(User).filter(User.email == "test@example.com").one()


def _application(db, user, *, external_id: str) -> Application:
    job = Job(
        title="Fraud Operations Analyst",
        company="Example Financial",
        location="Ottawa, ON",
        source=JobSource.manual,
        status=JobStatus.applied,
        external_id=external_id,
    )
    db.add(job)
    db.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applied,
        automation_state="confirmed",
        application_target_status="resolved",
    )
    db.add(application)
    db.flush()
    return application


def test_manual_message_without_received_at_is_idempotent_by_source_reference(auth_client):
    db = TestingSessionLocal()
    try:
        user = _user(db)
        application = _application(db, user, external_id="phase9-source-dedupe")
        db.commit()
        application_id = application.id
    finally:
        db.close()

    payload = {
        "sender_name": "Talent Partner",
        "sender_email": "talent@example-financial.test",
        "subject": "Interview availability",
        "body": "We would like to schedule an interview next week.",
        "source_reference": "manual-email:stable-message-42",
    }
    first = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages",
        json=payload,
    )
    second = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages",
        json=payload,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert second.json()["event_id"] == first.json()["event_id"]

    db = TestingSessionLocal()
    try:
        assert (
            db.query(ApplicationEvent)
            .filter(
                ApplicationEvent.application_id == application_id,
                ApplicationEvent.event_type == "inbound_employer_message",
            )
            .count()
            == 1
        )
        assert (
            db.query(RecruiterInteraction)
            .filter(RecruiterInteraction.application_id == application_id)
            .count()
            == 1
        )
    finally:
        db.close()


def test_distinct_source_references_remain_distinct_messages(auth_client):
    db = TestingSessionLocal()
    try:
        user = _user(db)
        application = _application(db, user, external_id="phase9-source-distinct")
        db.commit()
        application_id = application.id
    finally:
        db.close()

    base = {
        "sender_email": "talent@example-financial.test",
        "subject": "Application status",
        "body": "Your application is still under review.",
    }
    first = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages",
        json={**base, "source_reference": "provider:message-a"},
    )
    second = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages",
        json={**base, "source_reference": "provider:message-b"},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is False
    assert first.json()["event_id"] != second.json()["event_id"]


def test_recruiter_email_matching_is_literal_not_sql_wildcard(auth_client):
    db = TestingSessionLocal()
    try:
        user = _user(db)
        application = _application(db, user, external_id="phase9-contact-literal")
        existing = RecruiterContact(
            user_id=user.id,
            company="Example Financial",
            full_name="Different Contact",
            email="talentXops@example-financial.test",
            relationship_stage="identified",
        )
        db.add(existing)
        db.commit()
        application_id = application.id
        existing_id = existing.id
    finally:
        db.close()

    response = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages",
        json={
            "sender_name": "Percent Address",
            "sender_email": "talent%ops@example-financial.test",
            "subject": "Interview",
            "body": "We would like to schedule an interview.",
            "source_reference": "provider:literal-email-address",
        },
    )

    assert response.status_code == 201
    assert response.json()["recruiter_contact_id"] != existing_id

    db = TestingSessionLocal()
    try:
        contacts = (
            db.query(RecruiterContact)
            .filter(
                RecruiterContact.user_id == user.id,
                RecruiterContact.company == "Example Financial",
            )
            .all()
        )
        assert {contact.email for contact in contacts} == {
            "talentXops@example-financial.test",
            "talent%ops@example-financial.test",
        }
    finally:
        db.close()
