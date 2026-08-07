from datetime import datetime, timedelta, timezone

from tests.conftest import TestingSessionLocal

from app.models.application import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    FollowUp,
    ManualReviewTask,
)
from app.models.evaluation import OpportunityEvaluation
from app.models.intelligence import (
    CareerMemory,
    KnowledgeEdge,
    KnowledgeNode,
    RecruiterContact,
    RecruiterInteraction,
)
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User


def _current_user(db):
    return db.query(User).filter(User.email == "test@example.com").one()


def _job(*, title="Operations Engineer", company="Acme", external_id="ops-1"):
    return Job(
        title=title,
        company=company,
        location="Ottawa, ON",
        source=JobSource.manual,
        status=JobStatus.approved,
        external_id=external_id,
        relevance_score=0.9,
    )


def test_operations_workspace_combines_owned_pipeline_timeline_agenda_and_evaluations(auth_client):
    db = TestingSessionLocal()
    try:
        user = _current_user(db)
        now = datetime.now(timezone.utc)
        job = _job()
        db.add(job)
        db.flush()

        application = Application(
            user_id=user.id,
            job_id=job.id,
            status=ApplicationStatus.interviewing,
            automation_state="confirmed",
            application_target_status="resolved",
            applied_at=now - timedelta(days=3),
            interview_at=now + timedelta(days=1),
        )
        db.add(application)
        db.flush()
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="application_status_changed",
                from_state="applied",
                to_state="interviewing",
            )
        )
        db.add(
            ManualReviewTask(
                application_id=application.id,
                reason_code="ambiguous_question",
                status="open",
                summary="Review one ambiguous application answer",
                expires_at=now + timedelta(hours=6),
            )
        )
        db.add(
            FollowUp(
                application_id=application.id,
                scheduled_at=now - timedelta(hours=1),
                subject="Following up",
                message="Draft only",
                recipient_email=None,
                status="needs_recipient",
                approval_status="unapproved",
            )
        )

        contact = RecruiterContact(
            user_id=user.id,
            company="Acme",
            full_name="Alex Recruiter",
            email="alex@acme.example",
            relationship_stage="conversation",
            next_followup_at=now + timedelta(hours=2),
        )
        db.add(contact)
        db.flush()
        db.add(
            RecruiterInteraction(
                contact_id=contact.id,
                application_id=application.id,
                direction="inbound",
                channel="email",
                interaction_type="reply",
                summary="Recruiter confirmed the interview window.",
                occurred_at=now - timedelta(hours=2),
            )
        )
        db.add(
            OpportunityEvaluation(
                user_id=user.id,
                job_id=job.id,
                application_id=application.id,
                framework_version="jobtomatik-opportunity-v1",
                recommendation="strong_match",
                weighted_score=4.35,
                dimension_scores={
                    "north_star_alignment": 4.5,
                    "cv_match": 4.2,
                },
                analysis_blocks={},
                legitimacy_status="verified",
                hard_blockers=[],
                source_snapshot={"source": "test"},
            )
        )
        db.commit()
    finally:
        db.close()

    response = auth_client.get("/api/operations/workspace?agenda_days=14")
    assert response.status_code == 200
    data = response.json()

    assert data["summary"]["applications"] == 1
    assert data["summary"]["interviewing"] == 1
    interviewing = next(column for column in data["pipeline"] if column["status"] == "interviewing")
    assert interviewing["count"] == 1
    assert interviewing["items"][0]["company"] == "Acme"
    assert interviewing["items"][0]["open_review_count"] == 1

    timeline_kinds = {item["kind"] for item in data["timeline"]}
    assert timeline_kinds == {"application_event", "recruiter_interaction"}

    agenda_types = {item["item_type"] for item in data["agenda"]}
    assert {"interview", "manual_review", "followup_draft", "recruiter_followup"}.issubset(agenda_types)

    assert data["evaluations"][0]["application_id"] == interviewing["items"][0]["application_id"]
    assert data["evaluations"][0]["weighted_score"] == 4.35
    assert data["evaluations"][0]["dimension_scores"]["cv_match"] == 4.2


def test_operations_workspace_is_account_scoped(auth_client):
    db = TestingSessionLocal()
    try:
        user = _current_user(db)
        other = User(email="other@example.com", hashed_password="not-used", full_name="Other User")
        db.add(other)
        db.flush()

        own_job = _job(title="Owned Role", company="OwnedCo", external_id="owned-role")
        other_job = _job(title="Hidden Role", company="HiddenCo", external_id="hidden-role")
        db.add_all([own_job, other_job])
        db.flush()

        own_app = Application(user_id=user.id, job_id=own_job.id, status=ApplicationStatus.applied)
        other_app = Application(user_id=other.id, job_id=other_job.id, status=ApplicationStatus.offer)
        db.add_all([own_app, other_app])
        db.flush()
        db.add_all(
            [
                ApplicationEvent(application_id=own_app.id, event_type="owned_event"),
                ApplicationEvent(application_id=other_app.id, event_type="hidden_event"),
            ]
        )
        other_contact = RecruiterContact(
            user_id=other.id,
            company="HiddenCo",
            full_name="Hidden Recruiter",
            next_followup_at=datetime.now(timezone.utc),
        )
        db.add(other_contact)
        db.flush()
        db.add(
            RecruiterInteraction(
                contact_id=other_contact.id,
                interaction_type="reply",
                summary="Hidden interaction",
            )
        )
        db.commit()
    finally:
        db.close()

    response = auth_client.get("/api/operations/workspace")
    assert response.status_code == 200
    payload = response.json()
    serialized = str(payload)
    assert payload["summary"]["applications"] == 1
    assert "Owned Role" in serialized
    assert "Hidden Role" not in serialized
    assert "Hidden Recruiter" not in serialized
    assert "hidden_event" not in serialized


def test_memory_correction_preserves_prior_provenance_and_blocks_cross_account(auth_client):
    db = TestingSessionLocal()
    try:
        user = _current_user(db)
        other = User(email="memory-other@example.com", hashed_password="not-used")
        db.add(other)
        db.flush()
        memory = CareerMemory(
            user_id=user.id,
            kind="preference",
            key="remote_preference",
            content="Hybrid is acceptable",
            confidence=0.7,
            source="verified_import",
            source_ref="profile:preferences",
            memory_metadata={"origin": "profile"},
        )
        other_memory = CareerMemory(
            user_id=other.id,
            kind="preference",
            key="hidden",
            content="Hidden memory",
            confidence=1.0,
            source="user",
        )
        db.add_all([memory, other_memory])
        db.commit()
        db.refresh(memory)
        db.refresh(other_memory)
        memory_id = memory.id
        other_memory_id = other_memory.id
    finally:
        db.close()

    response = auth_client.patch(
        f"/api/operations/memories/{memory_id}",
        json={"content": "Remote-first is preferred", "confidence": 0.95, "is_active": True},
    )
    assert response.status_code == 200
    corrected = response.json()
    assert corrected["content"] == "Remote-first is preferred"
    assert corrected["confidence"] == 0.95
    assert corrected["source"] == "user_correction"
    history = corrected["memory_metadata"]["correction_history"]
    assert history[-1]["previous_content"] == "Hybrid is acceptable"
    assert history[-1]["previous_source"] == "verified_import"
    assert corrected["memory_metadata"]["corrected_by_user"] is True

    forbidden = auth_client.patch(
        f"/api/operations/memories/{other_memory_id}",
        json={"content": "Should not work"},
    )
    assert forbidden.status_code == 404


def test_operations_knowledge_edges_are_user_scoped(auth_client):
    db = TestingSessionLocal()
    try:
        user = _current_user(db)
        other = User(email="graph-other@example.com", hashed_password="not-used")
        db.add(other)
        db.flush()

        own_a = KnowledgeNode(user_id=user.id, node_type="company", label="Acme")
        own_b = KnowledgeNode(user_id=user.id, node_type="role", label="Engineer")
        hidden_a = KnowledgeNode(user_id=other.id, node_type="company", label="HiddenCo")
        hidden_b = KnowledgeNode(user_id=other.id, node_type="role", label="Hidden Role")
        db.add_all([own_a, own_b, hidden_a, hidden_b])
        db.flush()
        own_edge = KnowledgeEdge(
            user_id=user.id,
            from_node_id=own_a.id,
            to_node_id=own_b.id,
            relation="hires_for",
            weight=0.9,
            evidence={"source": "owned"},
        )
        hidden_edge = KnowledgeEdge(
            user_id=other.id,
            from_node_id=hidden_a.id,
            to_node_id=hidden_b.id,
            relation="hidden_relation",
            weight=1.0,
            evidence={"source": "hidden"},
        )
        db.add_all([own_edge, hidden_edge])
        db.commit()
        own_edge_id = own_edge.id
    finally:
        db.close()

    response = auth_client.get("/api/operations/knowledge/edges")
    assert response.status_code == 200
    edges = response.json()
    assert [edge["id"] for edge in edges] == [own_edge_id]
    assert edges[0]["relation"] == "hires_for"
    assert "hidden_relation" not in str(edges)
