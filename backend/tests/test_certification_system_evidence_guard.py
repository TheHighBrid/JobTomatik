from app.models.certification import CertificationEvidence
from app.services.certification_scale import canonical_hash, evidence_key_for, evidence_payload
from tests.conftest import TestingSessionLocal


def test_user_cannot_verify_system_scoped_evidence(auth_client):
    payload = evidence_payload(
        evidence_type="duplicate_prevention",
        adapter=None,
        commit_sha="d" * 40,
        environment="system-certification",
        status="passed",
        duration_seconds=None,
        source_reference="system:workflow:123",
        evidence_metadata={"report_sha256": "a" * 64},
    )
    db = TestingSessionLocal()
    try:
        record = CertificationEvidence(
            evidence_key=evidence_key_for(payload, owner_user_id=None),
            evidence_type="duplicate_prevention",
            adapter=None,
            commit_sha="d" * 40,
            environment="system-certification",
            status="passed",
            duration_seconds=None,
            source_reference="system:workflow:123",
            payload_hash=canonical_hash(payload),
            evidence_metadata={"report_sha256": "a" * 64},
            recorded_by_user_id=None,
            review_status="unreviewed",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        record_id = record.id
    finally:
        db.close()

    response = auth_client.post(
        f"/api/certification/evidence/{record_id}/verify",
        json={
            "acknowledgment": f"VERIFY EVIDENCE {record_id} {'d' * 12}",
            "review_reference": "user-must-not-verify-system-evidence",
        },
    )
    assert response.status_code == 403, response.text
