from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.application import Application, ApplicationStatus, FollowUp
from app.models.intelligence import RecruiterContact
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.supervised_followup import (
    STATUS_DRAFT,
    STATUS_SENDING,
    SupervisedFollowUpError,
    approval_acknowledgment,
    approve_followup,
    reserve_followup_delivery,
)


def test_stale_second_worker_cannot_claim_same_approved_payload(db_session, monkeypatch):
    from app.services import supervised_followup

    monkeypatch.setattr(supervised_followup.settings, "allow_real_followup_send", True)
    monkeypatch.setattr(supervised_followup.settings, "sendgrid_api_key", "test-key")

    user = User(
        email="atomic-owner@example.com",
        hashed_password="not-used",
        full_name="Atomic Owner",
    )
    db_session.add(user)
    db_session.flush()

    job = Job(
        external_id="phase6-atomic-job",
        title="Fraud Analyst",
        company="Atomic Bank",
        location="Ottawa, Ontario",
        url="https://boards.greenhouse.io/atomic/jobs/1",
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
        submission_idempotency_key="phase6-atomic-application",
    )
    db_session.add(application)
    db_session.flush()

    contact = RecruiterContact(
        user_id=user.id,
        company=job.company,
        full_name="Atomic Recruiter",
        email="atomic-recruiter@example.test",
        relationship_stage="identified",
        relationship_score=0.5,
    )
    db_session.add(contact)
    db_session.flush()

    followup = FollowUp(
        application_id=application.id,
        recruiter_contact_id=contact.id,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        subject="Atomic reservation",
        message="Only one worker may claim this exact approved payload.",
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

    # Worker B reads the approved row, then closes its read transaction while keeping
    # the ORM snapshot in memory. Worker A subsequently commits the authoritative claim.
    OtherSession = sessionmaker(
        bind=db_session.get_bind(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    other = OtherSession()
    try:
        stale_followup = other.query(FollowUp).filter(FollowUp.id == followup.id).one()
        stale_user = other.query(User).filter(User.id == user.id).one()
        assert stale_followup.status == "approved"
        other.commit()

        reserve_followup_delivery(db_session, followup, user)
        db_session.commit()
        assert followup.status == STATUS_SENDING
        assert followup.send_attempt_count == 1

        with pytest.raises(SupervisedFollowUpError, match="already claimed|payload changed"):
            reserve_followup_delivery(other, stale_followup, stale_user)
        other.rollback()

        db_session.expire_all()
        persisted = db_session.query(FollowUp).filter(FollowUp.id == followup.id).one()
        assert persisted.status == STATUS_SENDING
        assert persisted.send_attempt_count == 1
    finally:
        other.close()
