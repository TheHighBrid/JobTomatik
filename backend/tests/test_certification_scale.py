from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect

from app.config import get_settings
from app.models.certification import CertificationEvidence, ReleaseAuthorization
from app.models.user import User
from app.services import certification_scale
from app.services.certification_scale import (
    AUTONOMOUS_PILOT_REQUIREMENTS,
    build_release_track,
)
from app.services.operations_policy import operations_readiness_manifest
from tests.conftest import TestingSessionLocal


REVISION = "a" * 40
OTHER_REVISION = "b" * 40


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
            "artifact_name": "jobtomatik-v2.apk",
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


def _record(auth_client, evidence_type: str, *, revision: str = REVISION, suffix: str = "primary"):
    response = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": evidence_type,
            "commit_sha": revision,
            "environment": "certification-test",
            "status": "passed",
            "duration_seconds": _duration_for(evidence_type),
            "source_reference": f"test:{evidence_type}:{suffix}",
            "evidence_metadata": _metadata_for(evidence_type),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _verify(auth_client, record: dict, *, revision: str, suffix: str = "primary"):
    response = auth_client.post(
        f"/api/certification/evidence/{record['evidence_id']}/verify",
        json={
            "acknowledgment": (
                f"VERIFY EVIDENCE {record['evidence_id']} {revision[:12]}"
            ),
            "review_reference": f"review:{record['evidence_type']}:{suffix}",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _record_and_verify(
    auth_client,
    evidence_type: str,
    *,
    revision: str = REVISION,
    suffix: str = "primary",
):
    record = _record(auth_client, evidence_type, revision=revision, suffix=suffix)
    assert record["review_status"] == "unreviewed"
    verified = _verify(auth_client, record, revision=revision, suffix=suffix)
    assert verified["review_status"] == "verified"
    return record


def _seed_pilot_prerequisites(auth_client, *, suffix: str) -> None:
    for evidence_type in AUTONOMOUS_PILOT_REQUIREMENTS:
        _record_and_verify(auth_client, evidence_type, suffix=suffix)


def test_certification_tables_are_part_of_test_runtime_schema():
    db = TestingSessionLocal()
    try:
        tables = set(inspect(db.get_bind()).get_table_names())
    finally:
        db.close()
    assert "certification_evidence" in tables
    assert "release_authorizations" in tables


def test_recording_evidence_is_unreviewed_and_does_not_enable_runtime(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    record = _record(auth_client, "duplicate_prevention", suffix="unreviewed")
    assert record["review_status"] == "unreviewed"

    manifest = auth_client.get("/api/certification/manifest").json()
    gate = manifest["tracks"]["autonomous_pilot"]["evidence"]["duplicate_prevention"]
    assert gate["qualifying"] is False
    assert "not_independently_verified" in gate["reasons"]
    assert manifest["runtime_controls"]["real_submission_enabled"] is False
    assert manifest["runtime_controls"]["autopilot_enabled"] is False


def test_verification_requires_exact_phrase_and_preserves_runtime_off(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    record = _record(auth_client, "confirmation_evidence", suffix="exact-ack")
    before_submit = get_settings().allow_real_application_submit
    before_auto = operations_readiness_manifest()["autopilot_enabled"]

    wrong = auth_client.post(
        f"/api/certification/evidence/{record['evidence_id']}/verify",
        json={"acknowledgment": "VERIFY", "review_reference": "review:wrong"},
    )
    assert wrong.status_code == 422

    verified = _verify(auth_client, record, revision=REVISION, suffix="exact-ack")
    assert verified["qualifying_for_current_head"] is True
    assert get_settings().allow_real_application_submit is before_submit is False
    assert operations_readiness_manifest()["autopilot_enabled"] is before_auto is False


def test_tampered_expired_and_wrong_head_evidence_fail_closed(monkeypatch, auth_client):
    _patch_revision(monkeypatch)

    tampered = _record(auth_client, "policy_controls", suffix="tampered")
    db = TestingSessionLocal()
    try:
        row = db.query(CertificationEvidence).filter(
            CertificationEvidence.id == tampered["evidence_id"]
        ).one()
        row.evidence_metadata = {"tampered": True}
        db.commit()
    finally:
        db.close()
    response = auth_client.post(
        f"/api/certification/evidence/{tampered['evidence_id']}/verify",
        json={
            "acknowledgment": (
                f"VERIFY EVIDENCE {tampered['evidence_id']} {REVISION[:12]}"
            ),
            "review_reference": "review:tampered",
        },
    )
    assert response.status_code == 409
    assert "payload_hash_mismatch" in str(response.json()["detail"])

    expired = auth_client.post(
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
    expired_review = auth_client.post(
        f"/api/certification/evidence/{expired['evidence_id']}/verify",
        json={
            "acknowledgment": (
                f"VERIFY EVIDENCE {expired['evidence_id']} {REVISION[:12]}"
            ),
            "review_reference": "review:expired",
        },
    )
    assert expired_review.status_code == 409
    assert "evidence_expired" in str(expired_review.json()["detail"])

    old = _record_and_verify(
        auth_client,
        "handoff_notifications",
        revision=OTHER_REVISION,
        suffix="old-head",
    )
    assert old["commit_sha"] == OTHER_REVISION
    manifest = auth_client.get("/api/certification/manifest").json()
    old_gate = manifest["tracks"]["autonomous_pilot"]["evidence"]["handoff_notifications"]
    assert old_gate["qualifying"] is False
    assert "not_exact_candidate_head" in old_gate["reasons"]


def test_shadow_evidence_requires_no_submit_metadata_and_measured_duration(monkeypatch, auth_client):
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
    ).json()
    short_review = auth_client.post(
        f"/api/certification/evidence/{short['evidence_id']}/verify",
        json={
            "acknowledgment": (
                f"VERIFY EVIDENCE {short['evidence_id']} {REVISION[:12]}"
            ),
            "review_reference": "review:short-shadow",
        },
    )
    assert short_review.status_code == 409
    assert "duration_below_minimum" in str(short_review.json()["detail"])


def test_evidence_is_account_scoped(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    _record_and_verify(auth_client, "duplicate_prevention", suffix="owner")
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


def test_pilot_authorization_requires_verified_prerequisites_exact_head_and_exact_phrase(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    premature = auth_client.post(
        "/api/certification/authorizations",
        json={
            "scope": "autonomous_pilot",
            "release_version": "v2.00",
            "commit_sha": REVISION,
            "approval_reference": "owner:test:premature",
            "acknowledgment": f"AUTHORIZE AUTONOMOUS_PILOT v2.00 {REVISION[:12]}",
        },
    )
    assert premature.status_code == 409

    _seed_pilot_prerequisites(auth_client, suffix="pilot-ready")
    manifest = auth_client.get("/api/certification/manifest").json()
    assert manifest["tracks"]["autonomous_pilot"]["prerequisites_ready"] is True
    assert manifest["tracks"]["autonomous_pilot"]["owner_authorized"] is False

    wrong_head = auth_client.post(
        "/api/certification/authorizations",
        json={
            "scope": "autonomous_pilot",
            "release_version": "v2.00",
            "commit_sha": OTHER_REVISION,
            "approval_reference": "owner:test:wrong-head",
            "acknowledgment": (
                f"AUTHORIZE AUTONOMOUS_PILOT v2.00 {OTHER_REVISION[:12]}"
            ),
        },
    )
    assert wrong_head.status_code == 409

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

    before_submit = get_settings().allow_real_application_submit
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
    assert get_settings().allow_real_application_submit is before_submit is False
    assert operations_readiness_manifest()["autopilot_enabled"] is before_auto is False

    manifest = auth_client.get("/api/certification/manifest").json()
    assert manifest["tracks"]["autonomous_pilot"]["ready"] is True
    assert manifest["runtime_controls"]["real_submission_enabled"] is False
    assert manifest["runtime_controls"]["autopilot_enabled"] is False


def test_v2_release_requires_pilot_device_artifact_and_checksum(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    _seed_pilot_prerequisites(auth_client, suffix="v2-base")
    manifest = auth_client.get("/api/certification/manifest").json()
    track = manifest["tracks"]["v2_release"]
    for required in (
        "autonomous_pilot",
        "android_device_acceptance",
        "release_artifact",
        "release_checksum",
    ):
        assert track["evidence"][required]["qualifying"] is False
        assert track["evidence"][required]["reasons"] == ["missing"]

    bad_artifact = auth_client.post(
        "/api/certification/evidence",
        json={
            "evidence_type": "release_artifact",
            "commit_sha": REVISION,
            "environment": "test",
            "status": "passed",
            "source_reference": "test:bad-artifact",
            "evidence_metadata": {
                "artifact_name": "build.apk",
                "artifact_kind": "unknown",
            },
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


def test_authorization_revocation_and_expiry_fail_closed(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    _seed_pilot_prerequisites(auth_client, suffix="revoke")
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
    assert auth_client.get("/api/certification/manifest").json()["tracks"]["autonomous_pilot"]["ready"] is False

    db = TestingSessionLocal()
    try:
        user_id = db.query(User).filter(User.email == "test@example.com").one().id
        expired = ReleaseAuthorization(
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
        db.add(expired)
        db.commit()
        track = build_release_track(
            db,
            user_id=user_id,
            scope="autonomous_pilot",
            release_version="v2.00",
            revision=REVISION,
        )
        assert track["owner_authorized"] is False
    finally:
        db.close()
