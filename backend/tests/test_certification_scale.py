from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect

from app.config import get_settings
from app.database import engine
from app.models.certification import CertificationEvidence, ReleaseAuthorization
from app.models.user import User
from app.services import certification_scale
from app.services.certification_scale import (
    AUTONOMOUS_PILOT_REQUIREMENTS,
    V2_RELEASE_REQUIREMENTS,
    build_release_track,
)
from app.services.operations_policy import operations_readiness_manifest
from tests.conftest import TestingSessionLocal


REVISION = "a" * 40
OTHER_REVISION = "b" * 40


def _user_id() -> int:
    db = TestingSessionLocal()
    try:
        return db.query(User).filter(User.email == "test@example.com").one().id
    finally:
        db.close()


def _patch_revision(monkeypatch, revision: str = REVISION) -> None:
    monkeypatch.setattr(certification_scale, "current_revision", lambda: revision)
    import app.api.certification as certification_api

    monkeypatch.setattr(certification_api, "current_revision", lambda: revision)


def _metadata_for(evidence_type: str) -> dict:
    if evidence_type.startswith("shadow_run_"):
        return {
            "final_submit_enabled": False,
            "final_submit_clicked": False,
            "measured_elapsed_time": True,
            "report_sha256": "1" * 64,
        }
    if evidence_type == "release_artifact":
        return {
            "artifact_name": "jobtomatik-v2-debug.apk",
            "artifact_kind": "android_apk",
        }
    if evidence_type == "release_checksum":
        return {"algorithm": "sha256", "digest": "2" * 64}
    return {"test_fixture": True, "final_submit_clicked": False}


def _duration_for(evidence_type: str) -> int | None:
    return {
        "shadow_run_4h": 4 * 60 * 60,
        "shadow_run_8h": 8 * 60 * 60,
        "shadow_run_24h": 24 * 60 * 60,
    }.get(evidence_type)


def _record_and_verify(auth_client, evidence_type: str, *, revision: str = REVISION, suffix: str = "") -> int:
    response = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": evidence_type,
            "commit_sha": revision,
            "environment": "certification-test",
            "status": "passed",
            "duration_seconds": _duration_for(evidence_type),
            "source_reference": f"test:{evidence_type}:{suffix or 'primary'}",
            "evidence_metadata": _metadata_for(evidence_type),
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["review_status"] == "unreviewed"
    evidence_id = data["evidence_id"]
    verified = auth_client.post(
        f"/api/certification/evidence/{evidence_id}/verify",
        json={
            "acknowledgment": f"VERIFY EVIDENCE {evidence_id} {revision[:12]}",
            "review_reference": f"test-review:{evidence_type}:{suffix or 'primary'}",
        },
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["review_status"] == "verified"
    return evidence_id


def _seed_scope(auth_client, requirements, *, revision: str = REVISION, suffix: str = "") -> None:
    for evidence_type in requirements:
        _record_and_verify(auth_client, evidence_type, revision=revision, suffix=suffix)


def test_certification_tables_are_part_of_runtime_schema():
    tables = set(inspect(engine).get_table_names())
    assert "certification_evidence" in tables
    assert "release_authorizations" in tables


def test_recorded_evidence_is_unreviewed_and_does_not_qualify(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    response = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": "duplicate_prevention",
            "commit_sha": REVISION,
            "environment": "test",
            "status": "passed",
            "source_reference": "test:unreviewed",
            "evidence_metadata": {"test_fixture": True},
        },
    )
    assert response.status_code == 201
    assert response.json()["review_status"] == "unreviewed"

    manifest = auth_client.get("/api/certification/manifest?release_version=v2.00")
    assert manifest.status_code == 200
    gate = manifest.json()["tracks"]["autonomous_pilot"]["evidence"]["duplicate_prevention"]
    assert gate["qualifying"] is False
    assert "not_independently_verified" in gate["reasons"]
    assert manifest.json()["runtime_controls"]["real_submission_enabled"] is False


def test_review_requires_exact_acknowledgment_and_does_not_enable_runtime(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    before_submission = get_settings().allow_real_application_submit
    before_autopilot = operations_readiness_manifest()["autopilot_enabled"]
    created = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": "confirmation_evidence",
            "commit_sha": REVISION,
            "environment": "test",
            "status": "passed",
            "source_reference": "test:review-ack",
            "evidence_metadata": {"verified_source": "fixture"},
        },
    ).json()

    wrong = auth_client.post(
        f"/api/certification/evidence/{created['evidence_id']}/verify",
        json={"acknowledgment": "VERIFY", "review_reference": "review:test"},
    )
    assert wrong.status_code == 422

    right = auth_client.post(
        f"/api/certification/evidence/{created['evidence_id']}/verify",
        json={
            "acknowledgment": f"VERIFY EVIDENCE {created['evidence_id']} {REVISION[:12]}",
            "review_reference": "review:test",
        },
    )
    assert right.status_code == 200
    assert right.json()["qualifying_for_current_head"] is True
    assert get_settings().allow_real_application_submit is before_submission is False
    assert operations_readiness_manifest()["autopilot_enabled"] is before_autopilot is False


def test_tampered_evidence_fails_closed_during_review(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    created = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": "policy_controls",
            "commit_sha": REVISION,
            "environment": "test",
            "status": "passed",
            "source_reference": "test:tamper",
            "evidence_metadata": {"caps": True},
        },
    ).json()

    db = TestingSessionLocal()
    try:
        record = db.query(CertificationEvidence).filter(CertificationEvidence.id == created["evidence_id"]).one()
        record.evidence_metadata = {"caps": False, "tampered": True}
        db.commit()
    finally:
        db.close()

    response = auth_client.post(
        f"/api/certification/evidence/{created['evidence_id']}/verify",
        json={
            "acknowledgment": f"VERIFY EVIDENCE {created['evidence_id']} {REVISION[:12]}",
            "review_reference": "review:tamper",
        },
    )
    assert response.status_code == 409
    assert "payload_hash_mismatch" in str(response.json()["detail"])


def test_verified_evidence_for_old_head_does_not_qualify_current_head(monkeypatch, auth_client):
    _patch_revision(monkeypatch, REVISION)
    evidence_id = _record_and_verify(auth_client, "handoff_notifications", revision=OTHER_REVISION)
    evidence = auth_client.get("/api/certification/evidence").json()
    row = next(item for item in evidence if item["evidence_id"] == evidence_id)
    assert row["review_status"] == "verified"

    manifest = auth_client.get("/api/certification/manifest").json()
    gate = manifest["tracks"]["autonomous_pilot"]["evidence"]["handoff_notifications"]
    assert gate["qualifying"] is False
    assert "not_exact_candidate_head" in gate["reasons"]


def test_expired_evidence_fails_closed(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    created = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": "monitoring_alerting",
            "commit_sha": REVISION,
            "environment": "test",
            "status": "passed",
            "source_reference": "test:expired",
            "evidence_metadata": {"monitoring": True},
            "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        },
    ).json()
    response = auth_client.post(
        f"/api/certification/evidence/{created['evidence_id']}/verify",
        json={
            "acknowledgment": f"VERIFY EVIDENCE {created['evidence_id']} {REVISION[:12]}",
            "review_reference": "review:expired",
        },
    )
    assert response.status_code == 409
    assert "evidence_expired" in str(response.json()["detail"])


def test_shadow_evidence_requires_no_submit_proof_and_measured_minimum(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    unsafe = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": "shadow_run_4h",
            "commit_sha": REVISION,
            "environment": "test",
            "status": "passed",
            "duration_seconds": 4 * 60 * 60,
            "source_reference": "test:unsafe-shadow",
            "evidence_metadata": {
                "final_submit_enabled": True,
                "final_submit_clicked": False,
                "measured_elapsed_time": True,
            },
        },
    )
    assert unsafe.status_code == 422

    short = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": "shadow_run_4h",
            "commit_sha": REVISION,
            "environment": "test",
            "status": "passed",
            "duration_seconds": 60,
            "source_reference": "test:short-shadow",
            "evidence_metadata": _metadata_for("shadow_run_4h"),
        },
    )
    assert short.status_code == 201
    evidence_id = short.json()["evidence_id"]
    review = auth_client.post(
        f"/api/certification/evidence/{evidence_id}/verify",
        json={
            "acknowledgment": f"VERIFY EVIDENCE {evidence_id} {REVISION[:12]}",
            "review_reference": "review:short-shadow",
        },
    )
    assert review.status_code == 409
    assert "duration_below_minimum" in str(review.json()["detail"])


def test_certification_evidence_is_account_scoped(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    _record_and_verify(auth_client, "duplicate_prevention")
    db = TestingSessionLocal()
    try:
        other = User(email="phase10-other@example.com", hashed_password="unused")
        db.add(other)
        db.commit()
        track = build_release_track(
            db,
            user_id=other.id,
            scope="autonomous_pilot",
            release_version="v2.00",
            revision=REVISION,
        )
        assert track["evidence"]["duplicate_prevention"]["qualifying"] is False
        assert track["evidence"]["duplicate_prevention"]["reasons"] == ["missing"]
    finally:
        db.close()


def test_autonomous_pilot_authorization_requires_all_verified_exact_head_evidence(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    missing = auth_client.post(
        "/api/certification/authorizations",
        json={
            "scope": "autonomous_pilot",
            "release_version": "v2.00",
            "commit_sha": REVISION,
            "approval_reference": "owner:test:premature",
            "acknowledgment": f"AUTHORIZE AUTONOMOUS_PILOT v2.00 {REVISION[:12]}",
        },
    )
    assert missing.status_code == 409
    assert "blockers" in missing.json()["detail"]

    _seed_scope(auth_client, AUTONOMOUS_PILOT_REQUIREMENTS, suffix="pilot-ready")
    before = auth_client.get("/api/certification/manifest").json()
    assert before["tracks"]["autonomous_pilot"]["prerequisites_ready"] is True
    assert before["tracks"]["autonomous_pilot"]["owner_authorized"] is False

    wrong_ack = auth_client.post(
        "/api/certification/authorizations",
        json={
            "scope": "autonomous_pilot",
            "release_version": "v2.00",
            "commit_sha": REVISION,
            "approval_reference": "owner:test:wrong-ack",
            "acknowledgment": "AUTHORIZE",
        },
    )
    assert wrong_ack.status_code == 422

    wrong_head = auth_client.post(
        "/api/certification/authorizations",
        json={
            "scope": "autonomous_pilot",
            "release_version": "v2.00",
            "commit_sha": OTHER_REVISION,
            "approval_reference": "owner:test:wrong-head",
            "acknowledgment": f"AUTHORIZE AUTONOMOUS_PILOT v2.00 {OTHER_REVISION[:12]}",
        },
    )
    assert wrong_head.status_code == 409

    before_real = get_settings().allow_real_application_submit
    before_auto = operations_readiness_manifest()["autopilot_enabled"]
    approved = auth_client.post(
        "/api/certification/authorizations",
        json={
            "scope": "autonomous_pilot",
            "release_version": "v2.00",
            "commit_sha": REVISION,
            "approval_reference": "owner:test:pilot-ready",
            "acknowledgment": f"AUTHORIZE AUTONOMOUS_PILOT v2.00 {REVISION[:12]}",
        },
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["runtime_enablement_changed"] is False
    assert get_settings().allow_real_application_submit is before_real is False
    assert operations_readiness_manifest()["autopilot_enabled"] is before_auto is False

    after = auth_client.get("/api/certification/manifest").json()
    assert after["tracks"]["autonomous_pilot"]["ready"] is True
    assert after["runtime_controls"]["real_submission_enabled"] is False
    assert after["runtime_controls"]["autopilot_enabled"] is False


def test_v2_release_remains_blocked_until_release_specific_evidence_exists(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    _seed_scope(auth_client, AUTONOMOUS_PILOT_REQUIREMENTS, suffix="release-base")
    manifest = auth_client.get("/api/certification/manifest").json()
    track = manifest["tracks"]["v2_release"]
    for required in (
        "autonomous_pilot",
        "android_device_acceptance",
        "release_artifact",
        "release_checksum",
    ):
        assert track["evidence"][required]["qualifying"] is False
        assert "missing" in track["evidence"][required]["reasons"]
    assert track["ready"] is False


def test_release_artifact_and_checksum_evidence_validate_metadata(auth_client):
    bad_artifact = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": "release_artifact",
            "commit_sha": REVISION,
            "environment": "test",
            "status": "passed",
            "source_reference": "test:bad-artifact",
            "evidence_metadata": {"artifact_name": "build.apk", "artifact_kind": "unknown"},
        },
    )
    assert bad_artifact.status_code == 422

    bad_checksum = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": "release_checksum",
            "commit_sha": REVISION,
            "environment": "test",
            "status": "passed",
            "source_reference": "test:bad-checksum",
            "evidence_metadata": {"algorithm": "md5", "digest": "abc"},
        },
    )
    assert bad_checksum.status_code == 422


def test_release_authorization_can_be_revoked_without_runtime_side_effect(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    _seed_scope(auth_client, AUTONOMOUS_PILOT_REQUIREMENTS, suffix="revoke")
    approved = auth_client.post(
        "/api/certification/authorizations",
        json={
            "scope": "autonomous_pilot",
            "release_version": "v2.00",
            "commit_sha": REVISION,
            "approval_reference": "owner:test:revoke",
            "acknowledgment": f"AUTHORIZE AUTONOMOUS_PILOT v2.00 {REVISION[:12]}",
        },
    )
    assert approved.status_code == 201
    authorization_id = approved.json()["authorization_id"]
    wrong = auth_client.post(
        f"/api/certification/authorizations/{authorization_id}/revoke",
        json={"acknowledgment": "REVOKE", "reason": "test"},
    )
    assert wrong.status_code == 422
    revoked = auth_client.post(
        f"/api/certification/authorizations/{authorization_id}/revoke",
        json={
            "acknowledgment": f"REVOKE AUTHORIZATION {authorization_id}",
            "reason": "test rollback",
        },
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert revoked.json()["runtime_enablement_changed"] is False
    manifest = auth_client.get("/api/certification/manifest").json()
    assert manifest["tracks"]["autonomous_pilot"]["owner_authorized"] is False
    assert manifest["tracks"]["autonomous_pilot"]["ready"] is False


def test_expired_release_authorization_is_ignored(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    user_id = _user_id()
    db = TestingSessionLocal()
    try:
        authorization = ReleaseAuthorization(
            scope="autonomous_pilot",
            release_version="v2.00",
            commit_sha=REVISION,
            approval_reference="owner:test:expired-auth",
            payload_hash="3" * 64,
            status="approved",
            approved_by_user_id=user_id,
            approved_at=datetime.now(timezone.utc) - timedelta(hours=2),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            authorization_metadata={"runtime_enablement_changed": False},
        )
        db.add(authorization)
        db.commit()
        track = build_release_track(
            db,
            user_id=user_id,
            scope="autonomous_pilot",
            release_version="v2.00",
            revision=REVISION,
        )
        assert track["owner_authorized"] is False
        assert "owner_authorization:missing" in track["blockers"]
    finally:
        db.close()
