from datetime import datetime, timedelta, timezone

from app.models.application import Application, ApplicationStatus, FollowUp
from app.models.intelligence import RecruiterContact
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.supervised_followup import (
    APPROVAL_ACTIVE,
    APPROVAL_CONSUMED,
    STATUS_DELIVERY_UNCERTAIN,
    STATUS_SENDING,
)
from app.tasks.followup import _recover_stale_followup_deliveries


def _sending_followup(db_session, user, *, suffix: str, age_minutes: int) -> FollowUp:
    job = Job(
        external_id=f"phase6-recovery-{suffix}",
        title="Fraud Analyst",
        company="Recovery Bank",
        location="Ottawa, Ontario",
        url=f"https://boards.greenhouse.io/recovery/jobs/{suffix}",
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
        submission_idempotency_key=f"phase6-recovery-submit-{suffix}",
    )
    db_session.add(application)
    db_session.flush()

    contact = RecruiterContact(
        user_id=user.id,
        company=job.company,
        full_name=f"Recovery Recruiter {suffix}",
        email=f"recovery-{suffix}@example.test",
        relationship_stage="identified",
        relationship_score=0.5,
    )
    db_session.add(contact)
    db_session.flush()

    followup = FollowUp(
        application_id=application.id,
        recruiter_contact_id=contact.id,
        scheduled_at=datetime.now(timezone.utc) - timedelta(hours=1),
        subject="Recovery follow-up",
        message="A reserved message whose provider outcome must not be guessed.",
        recipient_email=contact.email,
        status=STATUS_SENDING,
        approval_status=APPROVAL_ACTIVE,
        approval_reference=f"approval-{suffix}",
        approval_payload_hash=f"payload-{suffix}",
        payload_hash=f"payload-{suffix}",
        last_send_attempt_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
        send_attempt_count=1,
        delivery_metadata={
            "reservation": {
                "approval_reference": f"approval-{suffix}",
                "payload_hash": f"payload-{suffix}",
            }
        },
    )
    db_session.add(followup)
    db_session.flush()
    return followup


def test_stale_sending_reservation_becomes_uncertain_without_retry(db_session):
    user = User(
        email="recovery-owner@example.com",
        hashed_password="not-used",
        full_name="Recovery Owner",
    )
    db_session.add(user)
    db_session.flush()

    stale = _sending_followup(db_session, user, suffix="stale", age_minutes=20)
    recent = _sending_followup(db_session, user, suffix="recent", age_minutes=5)
    db_session.commit()

    result = _recover_stale_followup_deliveries()
    assert result["recovered"] == 1
    assert result["followup_ids"] == [stale.id]
    assert result["automatic_retry_allowed"] is False

    db_session.expire_all()
    stale_row = db_session.query(FollowUp).filter(FollowUp.id == stale.id).one()
    recent_row = db_session.query(FollowUp).filter(FollowUp.id == recent.id).one()

    assert stale_row.status == STATUS_DELIVERY_UNCERTAIN
    assert stale_row.approval_status == APPROVAL_CONSUMED
    assert stale_row.sent_at is None
    assert stale_row.send_attempt_count == 1
    assert stale_row.delivery_metadata["delivery"]["uncertain"] is True
    assert stale_row.delivery_metadata["delivery"]["payload_hash"] == "payload-stale"

    assert recent_row.status == STATUS_SENDING
    assert recent_row.approval_status == APPROVAL_ACTIVE
    assert recent_row.send_attempt_count == 1
