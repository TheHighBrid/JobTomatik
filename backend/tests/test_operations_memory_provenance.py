from tests.conftest import TestingSessionLocal

from app.models.intelligence import CareerMemory
from app.models.user import User


def _current_user(db):
    return db.query(User).filter(User.email == "test@example.com").one()


def test_memory_correction_gets_new_source_reference_and_noop_save_does_not_churn_history(auth_client):
    db = TestingSessionLocal()
    try:
        user = _current_user(db)
        memory = CareerMemory(
            user_id=user.id,
            kind="achievement",
            key="impact",
            content="Improved reliability",
            confidence=0.8,
            source="verified_import",
            source_ref="resume:line:42",
            memory_metadata={},
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        memory_id = memory.id
    finally:
        db.close()

    first = auth_client.patch(
        f"/api/operations/memories/{memory_id}",
        json={"content": "Improved runtime reliability", "confidence": 0.9},
    )
    assert first.status_code == 200
    corrected = first.json()
    assert corrected["source"] == "user_correction"
    assert corrected["source_ref"] == f"operations:career_memory:{memory_id}:user_correction"
    assert len(corrected["memory_metadata"]["correction_history"]) == 1
    assert corrected["memory_metadata"]["correction_history"][0]["previous_source_ref"] == "resume:line:42"

    second = auth_client.patch(
        f"/api/operations/memories/{memory_id}",
        json={"content": "Improved runtime reliability", "confidence": 0.9, "is_active": False},
    )
    assert second.status_code == 200
    no_op_fact = second.json()
    assert no_op_fact["is_active"] is False
    assert len(no_op_fact["memory_metadata"]["correction_history"]) == 1
    assert no_op_fact["source"] == "user_correction"
    assert no_op_fact["source_ref"] == f"operations:career_memory:{memory_id}:user_correction"
