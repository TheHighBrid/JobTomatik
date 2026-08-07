from datetime import datetime, timedelta, timezone

from app.models.application import Application, ApplicationStatus, FollowUp
from app.models.intelligence import RecruiterContact
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.supervised_followup import (
    APPROVAL_ACTIVE,
    STATUS_APPROVED,
    _as_utc,
    build_followup_preflight,
)


def test_as_utc_normalizes_naive_and_aware_values():
    naive = datetime(2026, 8, 7, 12, 0, 0)
    eastern = datetime(2026, 8, 7, 8, 0, 0, tzinfo=timezone(timedelta(hours=-4)))

    assert _as_utc(naive) == datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)
    assert _as_utc(eastern) == datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)
    assert _as_utc(None) is None


def test_preflight_accepts_mixed_timezone_storage_without_comparison_errors(db_session):
    user = User(
        email="timezone-owner@example.com",
        hashed_password="not-used",
        full_name="Timezone Owner",
    )
    db_session.add(user)
    db_session.flush()

    job = Job(
        external_id="phase6-timezone-job",
        title="Fraud Analyst",
        company="Timezone Bank",
        location="Ottawa, Ontario",
        url="https://boards.greenhouse.io/timezone/jobs/1",
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
        submission_idempotency_key="phase6-timezone-application",
    )
    db_session.add(application)
    db_session.flush()

    contact = RecruiterContact(
        user_id=user.id,
        company=job.company,
        full_name="Timezone Recruiter",
        email="timezone-recruiter@example.test",
        relationship_stage="identified",
        relationship_score=0.5,
        next_followup_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    db_session.add(contact)
    db_session.flush()

    # SQLite may deserialize timezone=True columns as naive values while PostgreSQL
    # returns aware values. The service must safely normalize either representation.
    followup = FollowUp(
        application_id=application.id,
        recruiter_contact_id=contact.id,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        subject="Timezone-safe follow-up",
        message="This exact message should survive backend timezone differences.",
        recipient_email=contact.email,
        status=STATUS_APPROVED,
        approval_status=APPROVAL_ACTIVE,
        approval_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db_session.add(followup)
    db_session.commit()
    db_session.refresh(followup)

    # An active approval normally has a bound hash; make the current exact payload the
    # approved payload after the DB round-trip so the test isolates timestamp handling.
    initial = build_followup_preflight(db_session, followup, user)
    followup.payload_hash = initial["payload_hash"]
    followup.approval_payload_hash = initial["payload_hash"]
    db_session.commit()

    preflight = build_followup_preflight(db_session, followup, user)
    assert preflight["due"] is True
    assert preflight["payload_drifted"] is False
    assert preflight["approval_active"] is True
    assert preflight["scheduled_at"].endswith("+00:00")
    assert preflight["approval_expires_at"].endswith("+00:00")
