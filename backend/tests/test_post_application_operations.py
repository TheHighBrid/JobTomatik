from datetime import datetime, timedelta, timezone

from tests.conftest import TestingSessionLocal

from app.models.application import Application, ApplicationEvent, ApplicationStatus, FollowUp
from app.models.evaluation import OpportunityEvaluation
from app.models.intelligence import CareerMemory, KnowledgeNode, RecruiterContact, RecruiterInteraction
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services.post_application_operations import classify_employer_message


def _user(db):
    return db.query(User).filter(User.email == "test@example.com").one()


def _job(*, title="Fraud Prevention Advisor", company="Desjardins", external_id="phase9-job"):
    return Job(
        title=title,
        company=company,
        location="Ottawa, ON",
        source=JobSource.manual,
        status=JobStatus.applied,
        external_id=external_id,
        salary_min=80000,
        salary_max=110000,
        salary_currency="CAD",
        requirements=(
            "Investigate fraud patterns and make evidence-based decisions. "
            "Communicate clearly with customers and internal partners. "
            "Use risk judgment while following documented controls."
        ),
    )


def _application(db, user, *, status=ApplicationStatus.applied, external_id="phase9-job"):
    job = _job(external_id=external_id)
    db.add(job)
    db.flush()
    application = Application(
        user_id=user.id,
        job_id=job.id,
        status=status,
        automation_state="confirmed",
        application_target_status="resolved",
        applied_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    db.add(application)
    db.flush()
    return application


def test_classifier_is_deterministic_and_only_proposes_status():
    result = classify_employer_message(
        "Interview availability",
        "We would like to invite you to interview and schedule a call with the team.",
    )
    assert result["category"] == "interview"
    assert result["proposed_status"] == "interviewing"
    assert result["requires_confirmation"] is True
    assert result["confidence"] >= 0.8
    assert result["classifier_version"] == "post-application-rules-v1"


def test_inbound_interview_message_attaches_to_owned_application_without_auto_status_change(auth_client):
    db = TestingSessionLocal()
    try:
        user = _user(db)
        application = _application(db, user)
        db.commit()
        application_id = application.id
    finally:
        db.close()

    payload = {
        "sender_name": "Amina Recruiter",
        "sender_email": "amina@desjardins.example",
        "subject": "Interview availability",
        "body": "We would like to invite you to interview. Please share your interview availability.",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "source_reference": "email:test-interview-1",
    }
    response = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages",
        json=payload,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["classification"]["category"] == "interview"
    assert data["classification"]["proposed_status"] == "interviewing"
    assert data["duplicate"] is False
    assert data["recruiter_contact_id"] is not None
    assert data["recruiter_interaction_id"] is not None

    db = TestingSessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).one()
        assert application.status == ApplicationStatus.applied
        event = (
            db.query(ApplicationEvent)
            .filter(
                ApplicationEvent.application_id == application_id,
                ApplicationEvent.event_type == "inbound_employer_message",
            )
            .one()
        )
        assert event.payload["status_applied"] is False
        assert event.payload["source_reference"] == "email:test-interview-1"
        contact = db.query(RecruiterContact).filter(RecruiterContact.id == data["recruiter_contact_id"]).one()
        assert contact.company == "Desjardins"
        interaction = db.query(RecruiterInteraction).filter(
            RecruiterInteraction.id == data["recruiter_interaction_id"]
        ).one()
        assert interaction.direction == "inbound"
        assert interaction.interaction_type == "interview"
    finally:
        db.close()


def test_duplicate_inbound_message_is_idempotent(auth_client):
    db = TestingSessionLocal()
    try:
        user = _user(db)
        application = _application(db, user, external_id="phase9-dedupe")
        db.commit()
        application_id = application.id
    finally:
        db.close()

    received_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    payload = {
        "sender_name": "Recruiter",
        "sender_email": "recruiter@desjardins.example",
        "subject": "Application status",
        "body": "Your application is still under review.",
        "received_at": received_at,
        "source_reference": "email:dedupe-1",
    }
    first = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages", json=payload
    )
    second = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages", json=payload
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["duplicate"] is True
    assert second.json()["event_id"] == first.json()["event_id"]

    db = TestingSessionLocal()
    try:
        events = db.query(ApplicationEvent).filter(
            ApplicationEvent.application_id == application_id,
            ApplicationEvent.event_type == "inbound_employer_message",
        ).count()
        interactions = (
            db.query(RecruiterInteraction)
            .filter(RecruiterInteraction.application_id == application_id)
            .count()
        )
        assert events == 1
        assert interactions == 1
    finally:
        db.close()


def test_message_status_requires_exact_confirmation_and_preserves_provenance(auth_client):
    db = TestingSessionLocal()
    try:
        user = _user(db)
        application = _application(db, user, external_id="phase9-confirm")
        db.commit()
        application_id = application.id
    finally:
        db.close()

    message = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages",
        json={
            "sender_email": "talent@desjardins.example",
            "subject": "Interview invitation",
            "body": "We invite you to interview with our team next week.",
            "source_reference": "email:confirm-1",
        },
    )
    event_id = message.json()["event_id"]

    wrong = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages/{event_id}/apply-status",
        json={"acknowledgment": "confirm"},
    )
    assert wrong.status_code == 422

    confirmed = auth_client.post(
        f"/api/post-application/applications/{application_id}/messages/{event_id}/apply-status",
        json={"acknowledgment": "CONFIRM STATUS INTERVIEWING"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["to_status"] == "interviewing"

    db = TestingSessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).one()
        assert application.status == ApplicationStatus.interviewing
        confirmation = db.query(ApplicationEvent).filter(
            ApplicationEvent.id == confirmed.json()["event_id"]
        ).one()
        assert confirmation.event_type == "post_application_status_confirmed"
        assert confirmation.payload["source_reference"] == "email:confirm-1"
        assert confirmation.payload["source_message_event_id"] == event_id
    finally:
        db.close()


def test_cross_account_message_ingest_is_blocked(auth_client):
    db = TestingSessionLocal()
    try:
        other = User(email="phase9-other@example.com", hashed_password="unused")
        db.add(other)
        db.flush()
        hidden = _application(db, other, external_id="phase9-hidden")
        db.commit()
        hidden_id = hidden.id
    finally:
        db.close()

    response = auth_client.post(
        f"/api/post-application/applications/{hidden_id}/messages",
        json={
            "sender_email": "hidden@example.com",
            "subject": "Interview",
            "body": "Schedule an interview.",
            "source_reference": "email:hidden",
        },
    )
    assert response.status_code == 404


def test_interview_schedule_and_prep_use_only_recorded_evidence(auth_client):
    db = TestingSessionLocal()
    try:
        user = _user(db)
        application = _application(db, user, external_id="phase9-prep")
        db.add(
            CareerMemory(
                user_id=user.id,
                kind="experience",
                key="fraud_review",
                content="Reviewed fraud alerts and documented evidence-based decisions.",
                confidence=0.98,
                source="user_verified",
                source_ref="profile:experience:fraud",
            )
        )
        db.add(
            KnowledgeNode(
                user_id=user.id,
                node_type="company",
                label="Desjardins",
                payload={"note": "Cooperative financial group"},
                confidence=0.9,
                source_url="https://example.test/desjardins",
            )
        )
        db.commit()
        application_id = application.id
    finally:
        db.close()

    interview_at = datetime.now(timezone.utc) + timedelta(days=3)
    scheduled = auth_client.post(
        f"/api/post-application/applications/{application_id}/interview",
        json={
            "interview_at": interview_at.isoformat(),
            "interview_format": "video",
            "location_or_url": "https://meet.example.test/interview",
            "notes": "Panel interview",
            "source_reference": "calendar:user-confirmed-interview",
        },
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["status"] == "interviewing"

    prep = auth_client.get(
        f"/api/post-application/applications/{application_id}/interview-prep"
    )
    assert prep.status_code == 200
    data = prep.json()
    assert data["company"] == "Desjardins"
    assert data["requirements"]
    assert any(
        item["source_ref"] == "profile:experience:fraud"
        for item in data["candidate_evidence"]
    )
    assert any(item["label"] == "Desjardins" for item in data["company_context"])
    assert "must come from" in data["provenance_policy"]


def test_offer_outcome_creates_provenance_memory_and_offer_comparison(auth_client):
    db = TestingSessionLocal()
    try:
        user = _user(db)
        application = _application(
            db,
            user,
            status=ApplicationStatus.interviewing,
            external_id="phase9-offer",
        )
        db.add(
            OpportunityEvaluation(
                user_id=user.id,
                job_id=application.job_id,
                application_id=application.id,
                framework_version="jobtomatik-opportunity-v1",
                recommendation="strong_match",
                weighted_score=4.4,
                dimension_scores={"cv_match": 4.5},
                analysis_blocks={},
                legitimacy_status="verified",
                hard_blockers=[],
                source_snapshot={"source": "test"},
            )
        )
        db.commit()
        application_id = application.id
    finally:
        db.close()

    outcome = auth_client.post(
        f"/api/post-application/applications/{application_id}/outcome",
        json={
            "outcome": "offer",
            "salary_offered": 105000,
            "detail": "Written offer received",
            "source_reference": "offer:user-recorded-1",
        },
    )
    assert outcome.status_code == 200
    assert outcome.json()["outcome"] == "offer"
    assert outcome.json()["salary_offered"] == 105000

    offers = auth_client.get("/api/post-application/offers")
    assert offers.status_code == 200
    comparison = offers.json()
    assert comparison["offer_count"] == 1
    assert comparison["highest_salary_application_id"] == application_id
    assert comparison["highest_fit_application_id"] == application_id
    row = comparison["offers"][0]
    assert row["salary_offered"] == 105000
    assert row["market_salary_midpoint"] == 95000
    assert row["weighted_fit_score"] == 4.4
    assert "does not choose" in comparison["decision_note"]

    db = TestingSessionLocal()
    try:
        memory = db.query(CareerMemory).filter(
            CareerMemory.key == f"application_outcome:{application_id}"
        ).one()
        assert memory.source == "post_application_outcome"
        assert memory.source_ref.startswith(
            f"post_application:application:{application_id}:event:"
        )
        assert memory.memory_metadata["learning_scope"] == "observed_outcome_only"
    finally:
        db.close()


def test_workspace_surfaces_post_application_state_without_sending_followups(auth_client):
    db = TestingSessionLocal()
    try:
        user = _user(db)
        application = _application(db, user, external_id="phase9-workspace")
        db.add(
            FollowUp(
                application_id=application.id,
                scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
                subject="Follow-up draft",
                message="Not approved for sending",
                status="needs_recipient",
                approval_status="unapproved",
            )
        )
        db.commit()
    finally:
        db.close()

    response = auth_client.get("/api/post-application/workspace")
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["post_application_total"] >= 1
    assert payload["summary"]["followups_requiring_attention"] >= 1

    db = TestingSessionLocal()
    try:
        followup = db.query(FollowUp).filter(FollowUp.subject == "Follow-up draft").one()
        assert followup.status == "needs_recipient"
        assert followup.sent_at is None
        assert followup.approval_status == "unapproved"
    finally:
        db.close()
