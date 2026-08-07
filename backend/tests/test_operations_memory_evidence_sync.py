from tests.conftest import TestingSessionLocal

from app.models.intelligence import CareerMemory
from app.models.material import EvidenceUnit
from app.models.user import User
from app.services.evidence_ledger import rebuild_user_evidence


def _current_user(db):
    return db.query(User).filter(User.email == "test@example.com").one()


def _memory_evidence(db, user_id, memory_id):
    return (
        db.query(EvidenceUnit)
        .filter(
            EvidenceUnit.user_id == user_id,
            EvidenceUnit.source_type == "career_memory",
            EvidenceUnit.source_ref == f"career_memory:{memory_id}",
        )
        .order_by(EvidenceUnit.id.asc())
        .all()
    )


def test_operations_memory_correction_rebuilds_projected_evidence(auth_client):
    db = TestingSessionLocal()
    try:
        user = _current_user(db)
        memory = CareerMemory(
            user_id=user.id,
            kind="achievement",
            key="reliability",
            content="Reduced production incidents",
            confidence=0.8,
            source="verified_import",
            source_ref="resume:achievement:1",
        )
        db.add(memory)
        db.flush()
        rebuild_user_evidence(db, user)
        db.commit()
        db.refresh(memory)
        memory_id = memory.id
        user_id = user.id

        before = _memory_evidence(db, user_id, memory_id)
        assert len(before) == 1
        assert before[0].is_active is True
        assert before[0].statement == "Reduced production incidents"
        old_evidence_id = before[0].id
    finally:
        db.close()

    response = auth_client.patch(
        f"/api/operations/memories/{memory_id}",
        json={"content": "Reduced production incidents by improving runtime reliability", "confidence": 0.95},
    )
    assert response.status_code == 200

    db = TestingSessionLocal()
    try:
        projected = _memory_evidence(db, user_id, memory_id)
        assert len(projected) == 2
        old = next(item for item in projected if item.id == old_evidence_id)
        new = next(item for item in projected if item.id != old_evidence_id)
        assert old.is_active is False
        assert new.is_active is True
        assert new.statement == "Reduced production incidents by improving runtime reliability"
        assert new.confidence == 0.95
        assert new.provenance["career_memory_id"] == memory_id
        assert new.provenance["memory_source"] == "user_correction"
        assert new.provenance["memory_source_ref"] == f"operations:career_memory:{memory_id}:user_correction"
    finally:
        db.close()

    deactivate = auth_client.patch(
        f"/api/operations/memories/{memory_id}",
        json={"is_active": False},
    )
    assert deactivate.status_code == 200

    db = TestingSessionLocal()
    try:
        projected = _memory_evidence(db, user_id, memory_id)
        assert projected
        assert all(item.is_active is False for item in projected)
    finally:
        db.close()
