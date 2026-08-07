from datetime import datetime, timedelta, timezone

from app.models.application import Application, ApplicationStatus, FollowUp
from app.models.intelligence import RecruiterContact
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.supervised_followup import (
    STATUS_DRAFT,
    approval_acknowledgment,
    approve_followup,
    build_followup_preflight,
)
from app.tasks.followup import _deliver_followup


def _approved_followup(db_session):
    user = User(
        email="postapproval-owner@example.com",
        hashed_password="not-used",
        full_name="Post Approval Owner",
    )
    db_session.add(user)
    db_session.flush()

    job = Job(
        external_id="phase6-postapproval-job",
        title="Fraud Analyst",
        company="Post Approval Bank",
        location="Ottawa, Ontario",
        url="https://boards.greenhouse.io/postapproval/jobs/1",
        source=JobSource.greenhouse,
        status=JobStatus.applied,
    )
    db_session.add(job)
    db_session.flush()

    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applied,
        applied_at=datetime.now(timezone.utc) - timedelta(days=7),
        submission_idempotency_key="phase6-postapproval-application",
    )
    db_session.add(application)
    db_session.flush()

    contact = RecruiterContact(
        user_id=user.id,
        company=job.company,
        full_name="Post Approval Recruiter",
        email="postapproval-recruiter@example.test",
        relationship_stage="identified",
        relationship_score=0.5,
    )
    db_session.add(contact)
    db_session.flush()

    followup = FollowUp(
        application_id=application.id,
        recruiter_contact_id=contact.id,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        subject="Approved before status change",
        message="This message must not send after a new hard blocker appears.",
        recipient_email=contact.email,
        status=STATUS_DRAFT,
    )
    db_session.add(followup)
    db_session.flush()
    approve_followup(
        db_session,
        followup,
        user,
        acknowledgment=approval_acknowledgment(followup),
    )
    db_session.commit()
    return user, application, contact, followup


def test_application_status_change_blocks_delivery_after_payload_approval(
    db_session,
    monkeypatch,
):
    user, application, _, followup = _approved_followup(db_session)

    from app.services import supervised_followup
    from app.tasks import followup as followup_tasks

    monkeypatch.setattr(supervised_followup.settings, "allow_real_followup_send", True)
    monkeypatch.setattr(supervised_followup.settings, "sendgrid_api_key", "test-key")

    provider_called = False

    async def provider_should_not_run(**_kwargs):
        nonlocal provider_called
        provider_called = True
        return {"accepted": True, "status_code": 202, "message_id": "must-not-send"}

    monkeypatch.setattr(followup_tasks, "send_email_with_receipt", provider_should_not_run)

    application.status = ApplicationStatus.rejected
    db_session.commit()

    preflight = build_followup_preflight(db_session, followup, user)
    assert preflight["approval_active"] is True
    assert preflight["ready_for_delivery"] is False
    assert "application_not_followup_eligible" in preflight["blockers"]

    result = _deliver_followup(followup.id)
    assert result["status"] == "blocked"
    assert result["delivery_attempted"] is False
    assert "application_not_followup_eligible" in result["reason"]
    assert provider_called is False


def test_account_email_change_to_recipient_blocks_delivery_after_approval(db_session):
    user, _, contact, followup = _approved_followup(db_session)

    user.email = contact.email
    db_session.commit()

    preflight = build_followup_preflight(db_session, followup, user)
    assert preflight["ready_for_delivery"] is False
    assert "recipient_is_applicant_email" in preflight["blockers"]
