from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    FollowUp,
)
from app.models.intelligence import RecruiterContact, RecruiterInteraction
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.followup_schema import ensure_followup_schema
from app.services.supervised_followup import (
    APPROVAL_ACTIVE,
    APPROVAL_CONSUMED,
    APPROVAL_UNAPPROVED,
    STATUS_DELIVERY_UNCERTAIN,
    STATUS_DRAFT,
    STATUS_NEEDS_RECIPIENT,
    STATUS_SENT,
    SupervisedFollowUpError,
    approval_acknowledgment,
    approve_followup,
    build_followup_preflight,
    reset_followup_after_mutation,
)
from app.tasks.followup import _deliver_followup, schedule_auto_followup


def _build_application(db_session, user, *, suffix="one"):
    job = Job(
        external_id=f"phase6-{suffix}",
        title="Fraud Analyst",
        company="Example Bank",
        location="Ottawa, Ontario",
        url=f"https://boards.greenhouse.io/example/jobs/{suffix}",
        source=JobSource.greenhouse,
        status=JobStatus.applied,
        skills=["fraud", "investigation"],
        raw_data={"official_public_ats": True},
    )
    db_session.add(job)
    db_session.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.applied,
        automation_state=ApplicationAutomationState.submitted.value,
        application_target_url=job.url,
        application_target_status="resolved",
        submission_idempotency_key=f"phase6-submit-{user.id}-{suffix}",
        applied_at=datetime.utcnow() - timedelta(days=7),
    )
    db_session.add(application)
    db_session.flush()
    return application


def _build_ready_followup(db_session, user, *, suffix="one"):
    application = _build_application(db_session, user, suffix=suffix)
    contact = RecruiterContact(
        user_id=user.id,
        company=application.job.company,
        full_name="Riley Recruiter",
        title="Talent Partner",
        email=f"recruiter-{suffix}@examplebank.test",
        relationship_stage="identified",
        relationship_score=0.5,
        contact_metadata={"source": "user_confirmed"},
    )
    db_session.add(contact)
    db_session.flush()
    followup = FollowUp(
        application_id=application.id,
        recruiter_contact_id=contact.id,
        scheduled_at=datetime.utcnow() - timedelta(minutes=1),
        subject=f"Following up on {application.job.title}",
        message="Hello Riley, I am following up on my application. Best regards.",
        recipient_email=contact.email,
        status=STATUS_DRAFT,
        approval_status=APPROVAL_UNAPPROVED,
        delivery_metadata={"source": "phase6-test"},
    )
    db_session.add(followup)
    db_session.commit()
    db_session.refresh(followup)
    return application, contact, followup


def test_preflight_blocks_applicant_self_email(db_session):
    user = User(
        email="phase6-self@example.com",
        hashed_password="not-used",
        full_name="Phase Six Owner",
    )
    db_session.add(user)
    db_session.flush()
    _, _, followup = _build_ready_followup(db_session, user, suffix="self")
    followup.recipient_email = user.email
    db_session.commit()

    preflight = build_followup_preflight(db_session, followup, user)
    assert preflight["eligible_for_approval"] is False
    assert "recipient_is_applicant_email" in preflight["blockers"]
    assert preflight["ready_for_delivery"] is False


def test_exact_approval_binds_payload_and_edit_revokes_it(db_session):
    user = User(
        email="phase6-approval@example.com",
        hashed_password="not-used",
        full_name="Approval Owner",
    )
    db_session.add(user)
    db_session.flush()
    _, _, followup = _build_ready_followup(db_session, user, suffix="approval")

    with pytest.raises(SupervisedFollowUpError):
        approve_followup(db_session, followup, user, acknowledgment="APPROVE FOLLOWUP")

    approved = approve_followup(
        db_session,
        followup,
        user,
        acknowledgment=approval_acknowledgment(followup),
    )
    db_session.commit()
    assert approved["approval_active"] is True
    assert followup.approval_status == APPROVAL_ACTIVE
    assert followup.approval_payload_hash == approved["payload_hash"]
    prior_reference = followup.approval_reference

    reset_followup_after_mutation(
        db_session,
        followup,
        reason="test_edit",
        user_id=user.id,
    )
    followup.message = "A changed message requires a new approval."
    db_session.commit()

    assert followup.approval_status == APPROVAL_UNAPPROVED
    assert followup.approval_payload_hash is None
    assert followup.approval_reference == prior_reference
    assert followup.status == STATUS_DRAFT
    assert build_followup_preflight(db_session, followup, user)["approval_active"] is False


def test_auto_followup_only_prepares_draft_without_recipient(db_session):
    user = User(
        email="phase6-auto@example.com",
        hashed_password="not-used",
        full_name="Auto Draft Owner",
    )
    db_session.add(user)
    db_session.flush()
    application = _build_application(db_session, user, suffix="auto")
    db_session.commit()

    first = schedule_auto_followup.run(application.id, 7)
    second = schedule_auto_followup.run(application.id, 7)

    assert first["outreach_authorized"] is False
    assert first["delivery_attempted"] is False
    assert first["recipient_email"] is None
    assert second["idempotent"] is True
    assert second["followup_id"] == first["followup_id"]

    followup = db_session.query(FollowUp).filter(FollowUp.id == first["followup_id"]).one()
    assert followup.recipient_email is None
    assert followup.recruiter_contact_id is None
    assert followup.status == STATUS_NEEDS_RECIPIENT
    assert followup.approval_status == APPROVAL_UNAPPROVED


def test_delivery_is_blocked_while_global_followup_switch_is_off(db_session):
    user = User(
        email="phase6-off@example.com",
        hashed_password="not-used",
        full_name="Switch Owner",
    )
    db_session.add(user)
    db_session.flush()
    _, _, followup = _build_ready_followup(db_session, user, suffix="off")
    approve_followup(
        db_session,
        followup,
        user,
        acknowledgment=approval_acknowledgment(followup),
    )
    db_session.commit()

    result = _deliver_followup(followup.id)
    assert result["status"] == "blocked"
    assert result["delivery_attempted"] is False
    assert "disabled" in result["reason"].lower()

    db_session.expire_all()
    persisted = db_session.query(FollowUp).filter(FollowUp.id == followup.id).one()
    assert persisted.status != STATUS_SENT
    assert persisted.send_attempt_count == 0


def test_successful_delivery_is_one_time_and_records_recruiter_interaction(
    db_session,
    monkeypatch,
):
    user = User(
        email="phase6-send@example.com",
        hashed_password="not-used",
        full_name="Send Owner",
    )
    db_session.add(user)
    db_session.flush()
    application, contact, followup = _build_ready_followup(db_session, user, suffix="send")
    approve_followup(
        db_session,
        followup,
        user,
        acknowledgment=approval_acknowledgment(followup),
    )
    db_session.commit()

    from app.services import supervised_followup
    from app.tasks import followup as followup_tasks

    monkeypatch.setattr(supervised_followup.settings, "allow_real_followup_send", True)
    monkeypatch.setattr(supervised_followup.settings, "sendgrid_api_key", "test-key")

    async def accepted_receipt(**_kwargs):
        return {
            "accepted": True,
            "status_code": 202,
            "message_id": "provider-message-1",
            "provider": "sendgrid",
            "mode": "provider",
        }

    monkeypatch.setattr(followup_tasks, "send_email_with_receipt", accepted_receipt)

    first = _deliver_followup(followup.id)
    second = _deliver_followup(followup.id)
    assert first["status"] == STATUS_SENT
    assert first["delivery_attempted"] is True
    assert second["status"] == STATUS_SENT
    assert second["idempotent"] is True
    assert second["duplicate_delivery_prevented"] is True

    db_session.expire_all()
    persisted = db_session.query(FollowUp).filter(FollowUp.id == followup.id).one()
    assert persisted.status == STATUS_SENT
    assert persisted.approval_status == APPROVAL_CONSUMED
    assert persisted.send_attempt_count == 1
    assert persisted.sent_at is not None
    assert persisted.delivery_metadata["delivery"]["provider_message_id"] == "provider-message-1"
    assert (
        db_session.query(RecruiterInteraction)
        .filter(
            RecruiterInteraction.contact_id == contact.id,
            RecruiterInteraction.application_id == application.id,
        )
        .count()
        == 1
    )
    assert (
        db_session.query(ApplicationEvent)
        .filter(
            ApplicationEvent.application_id == application.id,
            ApplicationEvent.event_type == "supervised_followup_sent",
        )
        .count()
        == 1
    )


def test_provider_ambiguity_consumes_approval_and_prevents_automatic_retry(
    db_session,
    monkeypatch,
):
    user = User(
        email="phase6-uncertain@example.com",
        hashed_password="not-used",
        full_name="Uncertain Owner",
    )
    db_session.add(user)
    db_session.flush()
    _, _, followup = _build_ready_followup(db_session, user, suffix="uncertain")
    approve_followup(
        db_session,
        followup,
        user,
        acknowledgment=approval_acknowledgment(followup),
    )
    db_session.commit()

    from app.services import supervised_followup
    from app.tasks import followup as followup_tasks

    monkeypatch.setattr(supervised_followup.settings, "allow_real_followup_send", True)
    monkeypatch.setattr(supervised_followup.settings, "sendgrid_api_key", "test-key")

    async def uncertain_receipt(**_kwargs):
        return {
            "accepted": False,
            "status_code": 503,
            "message_id": None,
            "provider": "sendgrid",
            "mode": "provider",
            "error": "provider outcome uncertain",
        }

    monkeypatch.setattr(followup_tasks, "send_email_with_receipt", uncertain_receipt)

    first = _deliver_followup(followup.id)
    second = _deliver_followup(followup.id)
    assert first["status"] == STATUS_DELIVERY_UNCERTAIN
    assert first["automatic_retry_allowed"] is False
    assert second["status"] == "blocked"
    assert second["delivery_attempted"] is False

    db_session.expire_all()
    persisted = db_session.query(FollowUp).filter(FollowUp.id == followup.id).one()
    assert persisted.status == STATUS_DELIVERY_UNCERTAIN
    assert persisted.approval_status == APPROVAL_CONSUMED
    assert persisted.send_attempt_count == 1
    assert persisted.sent_at is None


def test_legacy_pending_followups_are_demoted_by_shared_schema_upgrade(tmp_path):
    database_path = tmp_path / "legacy-followups.db"
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE followups ("
                "id INTEGER PRIMARY KEY, "
                "application_id INTEGER NOT NULL, "
                "scheduled_at TIMESTAMP NOT NULL, "
                "sent_at TIMESTAMP, "
                "subject VARCHAR(500), "
                "message TEXT, "
                "recipient_email VARCHAR(255), "
                "status VARCHAR(50), "
                "created_at TIMESTAMP"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO followups "
                "(id, application_id, scheduled_at, recipient_email, status) "
                "VALUES (1, 10, :scheduled, 'recruiter@example.test', 'pending')"
            ),
            {"scheduled": datetime.utcnow()},
        )
        conn.execute(
            text(
                "INSERT INTO followups "
                "(id, application_id, scheduled_at, recipient_email, status) "
                "VALUES (2, 11, :scheduled, NULL, 'pending')"
            ),
            {"scheduled": datetime.utcnow()},
        )

    ensure_followup_schema(engine)
    columns = {item["name"] for item in inspect(engine).get_columns("followups")}
    assert "approval_status" in columns
    assert "send_idempotency_key" in columns
    assert "recruiter_contact_id" in columns

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, status, approval_status, send_idempotency_key "
                "FROM followups ORDER BY id"
            )
        ).fetchall()
    assert rows[0][1] == STATUS_DRAFT
    assert rows[1][1] == STATUS_NEEDS_RECIPIENT
    assert rows[0][2] == APPROVAL_UNAPPROVED
    assert rows[1][2] == APPROVAL_UNAPPROVED
    assert rows[0][3]
    assert rows[1][3]
    assert rows[0][3] != rows[1][3]


def test_followup_api_is_account_scoped_and_edits_revoke_approval(
    auth_client,
    db_session,
):
    owner = db_session.query(User).filter(User.email == "test@example.com").one()
    application = _build_application(db_session, owner, suffix="api")
    contact = RecruiterContact(
        user_id=owner.id,
        company=application.job.company,
        full_name="API Recruiter",
        title="Recruiter",
        email="api-recruiter@examplebank.test",
        relationship_stage="identified",
        relationship_score=0.5,
    )
    other = User(
        email="phase6-other@example.com",
        hashed_password="not-used",
        full_name="Other User",
    )
    db_session.add_all([contact, other])
    db_session.flush()
    foreign_contact = RecruiterContact(
        user_id=other.id,
        company=application.job.company,
        full_name="Foreign Recruiter",
        email="foreign@examplebank.test",
        relationship_stage="identified",
        relationship_score=0.5,
    )
    db_session.add(foreign_contact)
    db_session.commit()

    foreign = auth_client.post(
        f"/api/applications/{application.id}/followups",
        json={
            "scheduled_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "subject": "Follow-up",
            "message": "Message",
            "recruiter_contact_id": foreign_contact.id,
        },
    )
    assert foreign.status_code == 404

    self_addressed = auth_client.post(
        f"/api/applications/{application.id}/followups",
        json={
            "scheduled_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "subject": "Follow-up",
            "message": "Message",
            "recipient_email": owner.email,
        },
    )
    assert self_addressed.status_code == 409

    created = auth_client.post(
        f"/api/applications/{application.id}/followups",
        json={
            "scheduled_at": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "subject": "Following up on my application",
            "message": "Hello, I am following up on my application.",
            "recruiter_contact_id": contact.id,
        },
    )
    assert created.status_code == 201, created.text
    followup_id = created.json()["id"]
    assert created.json()["recipient_email"] == contact.email
    assert created.json()["approval_status"] == APPROVAL_UNAPPROVED

    preview = auth_client.get(
        f"/api/applications/{application.id}/followups/{followup_id}/preflight"
    )
    assert preview.status_code == 200
    expected = preview.json()["expected_acknowledgment"]
    assert expected == f"APPROVE FOLLOWUP {followup_id} TO {contact.email}"

    wrong = auth_client.post(
        f"/api/applications/{application.id}/followups/{followup_id}/approve",
        json={"acknowledgment": "APPROVE FOLLOWUP"},
    )
    assert wrong.status_code == 409

    approved = auth_client.post(
        f"/api/applications/{application.id}/followups/{followup_id}/approve",
        json={"acknowledgment": expected},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_active"] is True

    edited = auth_client.patch(
        f"/api/applications/{application.id}/followups/{followup_id}",
        json={"message": "Edited after approval, so consent must be revoked."},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["approval_status"] == APPROVAL_UNAPPROVED

    blocked_send = auth_client.post(
        f"/api/applications/{application.id}/followups/{followup_id}/send"
    )
    assert blocked_send.status_code == 409
