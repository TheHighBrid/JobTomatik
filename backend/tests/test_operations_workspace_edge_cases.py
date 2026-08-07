from tests.conftest import TestingSessionLocal

from app.models.application import Application, ApplicationStatus, ManualReviewTask
from app.models.intelligence import CareerMemory
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User


def _current_user(db):
    return db.query(User).filter(User.email == "test@example.com").one()


def test_open_review_summary_uses_full_dataset_not_pipeline_display_cap(auth_client):
    db = TestingSessionLocal()
    try:
        user = _current_user(db)
        for index in range(2):
            job = Job(
                title=f"Role {index}",
                company="Cap Test",
                external_id=f"cap-test-{index}",
                source=JobSource.manual,
                status=JobStatus.approved,
            )
            db.add(job)
            db.flush()
            application = Application(
                user_id=user.id,
                job_id=job.id,
                status=ApplicationStatus.applied,
            )
            db.add(application)
            db.flush()
            db.add(
                ManualReviewTask(
                    application_id=application.id,
                    reason_code="ambiguous_question",
                    status="open",
                    summary=f"Review {index}",
                )
            )
        db.commit()
    finally:
        db.close()

    response = auth_client.get("/api/operations/workspace?pipeline_limit_per_status=1")
    assert response.status_code == 200
    payload = response.json()
    applied = next(column for column in payload["pipeline"] if column["status"] == "applied")
    assert applied["count"] == 2
    assert len(applied["items"]) == 1
    assert payload["summary"]["open_reviews"] == 2


def test_memory_correction_rejects_whitespace_only_content(auth_client):
    db = TestingSessionLocal()
    try:
        user = _current_user(db)
        memory = CareerMemory(
            user_id=user.id,
            kind="fact",
            key="stable_fact",
            content="Keep this fact",
            confidence=1.0,
            source="user",
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        memory_id = memory.id
    finally:
        db.close()

    response = auth_client.patch(
        f"/api/operations/memories/{memory_id}",
        json={"content": "   \n\t  "},
    )
    assert response.status_code == 422

    db = TestingSessionLocal()
    try:
        memory = db.query(CareerMemory).filter(CareerMemory.id == memory_id).one()
        assert memory.content == "Keep this fact"
        assert memory.source == "user"
        assert not dict(memory.memory_metadata or {}).get("correction_history")
    finally:
        db.close()
