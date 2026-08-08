from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.certification import ReleaseAuthorization
from app.models.user import User
from app.services.certification_scale import (
    active_authorization,
    authorization_integrity_ok,
    authorization_payload,
    canonical_hash,
    evidence_key_for,
    evidence_payload,
)
from tests.conftest import TestingSessionLocal


REVISION = "c" * 40


def test_evidence_identity_is_namespaced_by_owner_account():
    payload = evidence_payload(
        evidence_type="duplicate_prevention",
        adapter=None,
        commit_sha=REVISION,
        environment="production-like",
        status="passed",
        duration_seconds=None,
        source_reference="workflow:12345",
        evidence_metadata={"report_sha256": "1" * 64},
    )

    first = evidence_key_for(payload, owner_user_id=101)
    same = evidence_key_for(payload, owner_user_id=101)
    second = evidence_key_for(payload, owner_user_id=202)
    system = evidence_key_for(payload, owner_user_id=None)

    assert first == same
    assert first != second
    assert first != system
    assert second != system


def test_active_authorization_rejects_hash_tampering():
    db = TestingSessionLocal()
    try:
        user = User(email="phase10-auth-integrity@example.com", hashed_password="unused")
        db.add(user)
        db.flush()
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=2)
        approval_reference = "owner:hash-bound-auth"
        body = authorization_payload(
            scope="autonomous_pilot",
            release_version="v2.00",
            commit_sha=REVISION,
            approved_by_user_id=user.id,
            approval_reference=approval_reference,
            expires_at=expires_at,
        )
        record = ReleaseAuthorization(
            scope="autonomous_pilot",
            release_version="v2.00",
            commit_sha=REVISION,
            approval_reference=approval_reference,
            payload_hash=canonical_hash(body),
            status="approved",
            approved_by_user_id=user.id,
            approved_at=now,
            expires_at=expires_at,
            authorization_metadata={"runtime_enablement_changed": False},
        )
        db.add(record)
        db.commit()
        db.refresh(record)

        assert authorization_integrity_ok(record) is True
        assert active_authorization(
            db,
            user_id=user.id,
            scope="autonomous_pilot",
            release_version="v2.00",
            revision=REVISION,
            now=now,
        ) is not None

        # Simulate database/state corruption after approval. The authorization must
        # become unusable rather than silently inheriting the changed expiry.
        record.expires_at = expires_at + timedelta(hours=8)
        db.commit()
        db.refresh(record)

        assert authorization_integrity_ok(record) is False
        assert active_authorization(
            db,
            user_id=user.id,
            scope="autonomous_pilot",
            release_version="v2.00",
            revision=REVISION,
            now=now,
        ) is None
    finally:
        db.close()
