from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.certification import CertificationEvidence, ShadowRunSession
from app.models.user import User
from app.services.certification_scale import (
    build_release_track,
    canonical_hash,
    evidence_is_qualifying,
    evidence_key_for,
    evidence_payload,
)
from app.services.shadow_evidence_provenance import shadow_evidence_provenance_reasons
from tests.conftest import TestingSessionLocal
from tests.test_certification_scale import (
    REVISION,
    _bridged_shadow_record,
    _patch_revision,
    _verify,
)


def _owner_id() -> int:
    db = TestingSessionLocal()
    try:
        return db.query(User).filter(User.email == "test@example.com").one().id
    finally:
        db.close()


def _evidence_row(evidence_id: int) -> CertificationEvidence:
    db = TestingSessionLocal()
    try:
        row = db.query(CertificationEvidence).filter(CertificationEvidence.id == evidence_id).one()
        db.expunge(row)
        return row
    finally:
        db.close()


def _linked_session(db, evidence_id: int) -> ShadowRunSession:
    return (
        db.query(ShadowRunSession)
        .filter(ShadowRunSession.certification_evidence_id == evidence_id)
        .one()
    )


def test_legacy_manual_shadow_record_cannot_be_verified(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    user_id = _owner_id()
    metadata = {
        "full_stack_shadow_session": True,
        "session_id": 999999,
        "report_sha256": "1" * 64,
        "measured_elapsed_time": True,
        "final_submit_enabled": False,
        "final_submit_clicked": False,
        "real_submission_remained_disabled": True,
        "qualification_eligible": True,
        "cycles_completed": 1,
        "cycles_failed": 0,
        "reconciled": True,
        "submission_authorized": False,
        "outreach_authorized": False,
    }
    payload = evidence_payload(
        evidence_type="shadow_run_4h",
        adapter=None,
        commit_sha=REVISION,
        environment="full-stack-shadow",
        status="passed",
        duration_seconds=4 * 60 * 60,
        source_reference="full-stack-shadow-session:999999:" + "1" * 64,
        evidence_metadata=metadata,
    )
    db = TestingSessionLocal()
    try:
        record = CertificationEvidence(
            evidence_key=evidence_key_for(payload, owner_user_id=user_id),
            evidence_type="shadow_run_4h",
            adapter=None,
            commit_sha=REVISION,
            environment="full-stack-shadow",
            status="passed",
            duration_seconds=4 * 60 * 60,
            source_reference=payload["source_reference"],
            payload_hash=canonical_hash(payload),
            evidence_metadata=metadata,
            recorded_by_user_id=user_id,
            review_status="unreviewed",
        )
        db.add(record)
        db.commit()
        evidence_id = record.id
    finally:
        db.close()

    response = auth_client.post(
        f"/api/certification/evidence/{evidence_id}/verify",
        json={
            "acknowledgment": f"VERIFY EVIDENCE {evidence_id} {REVISION[:12]}",
            "review_reference": "review:legacy-manual-shadow",
        },
    )
    assert response.status_code == 409, response.text
    assert "shadow_session_missing" in response.json()["detail"]["reasons"]


def test_post_verification_session_drift_blocks_release_track(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    record = _bridged_shadow_record(auth_client, "shadow_run_4h", suffix="post-review-drift")
    verified = _verify(auth_client, record, revision=REVISION, suffix="post-review-drift")
    assert verified["qualifying_for_current_head"] is True

    db = TestingSessionLocal()
    try:
        session = _linked_session(db, record["evidence_id"])
        session.cycles_failed = 1
        db.commit()

        track = build_release_track(
            db,
            user_id=session.user_id,
            scope="autonomous_pilot",
            release_version="v2.00",
            revision=REVISION,
        )
        gate = track["evidence"]["shadow_run_4h"]
        assert gate["qualifying"] is False
        assert "shadow_cycle_failure_present" in gate["reasons"]
        assert "shadow_report_cycle_failure_mismatch" in gate["reasons"]
    finally:
        db.close()


def test_post_verification_report_tamper_blocks_release_track(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    record = _bridged_shadow_record(auth_client, "shadow_run_4h", suffix="report-tamper")
    _verify(auth_client, record, revision=REVISION, suffix="report-tamper")

    db = TestingSessionLocal()
    try:
        session = _linked_session(db, record["evidence_id"])
        report = dict(session.final_report or {})
        quality = dict(report.get("quality") or {})
        quality["no_policy_escape"] = False
        report["quality"] = quality
        session.final_report = report
        db.commit()

        track = build_release_track(
            db,
            user_id=session.user_id,
            scope="autonomous_pilot",
            release_version="v2.00",
            revision=REVISION,
        )
        reasons = track["evidence"]["shadow_run_4h"]["reasons"]
        assert "shadow_report_hash_mismatch" in reasons
        assert "shadow_report_quality_gate_failed" in reasons
    finally:
        db.close()


def test_session_owner_drift_blocks_original_owner_manifest(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    record = _bridged_shadow_record(auth_client, "shadow_run_4h", suffix="owner-drift")
    _verify(auth_client, record, revision=REVISION, suffix="owner-drift")
    original_owner_id = _owner_id()

    db = TestingSessionLocal()
    try:
        other = User(email="phase12-other@example.com", hashed_password="unused", is_active=True)
        db.add(other)
        db.flush()
        session = _linked_session(db, record["evidence_id"])
        session.user_id = other.id
        db.commit()

        track = build_release_track(
            db,
            user_id=original_owner_id,
            scope="autonomous_pilot",
            release_version="v2.00",
            revision=REVISION,
        )
        reasons = track["evidence"]["shadow_run_4h"]["reasons"]
        assert "shadow_session_owner_mismatch" in reasons
        assert "shadow_session_expected_owner_mismatch" in reasons
    finally:
        db.close()


def test_duplicate_session_link_blocks_shadow_evidence(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    record = _bridged_shadow_record(auth_client, "shadow_run_4h", suffix="duplicate-link")
    _verify(auth_client, record, revision=REVISION, suffix="duplicate-link")

    db = TestingSessionLocal()
    try:
        original = _linked_session(db, record["evidence_id"])
        completed = datetime.now(timezone.utc)
        duplicate = ShadowRunSession(
            user_id=original.user_id,
            candidate_revision=REVISION,
            target_evidence_type="shadow_run_4h",
            requested_duration_seconds=4 * 60 * 60,
            cycle_interval_seconds=60,
            status="completed",
            started_at=completed - timedelta(hours=4),
            expected_end_at=completed,
            completed_at=completed,
            cycles_completed=1,
            cycles_failed=0,
            final_submit_allowed=False,
            stop_requested=False,
            configuration_snapshot={},
            baseline_snapshot={},
            final_report={},
            certification_evidence_id=record["evidence_id"],
        )
        db.add(duplicate)
        db.commit()

        track = build_release_track(
            db,
            user_id=original.user_id,
            scope="autonomous_pilot",
            release_version="v2.00",
            revision=REVISION,
        )
        assert "shadow_session_evidence_link_not_unique" in track["evidence"]["shadow_run_4h"]["reasons"]
    finally:
        db.close()


def test_malformed_report_duration_fails_closed_without_exception(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    record = _bridged_shadow_record(auth_client, "shadow_run_4h", suffix="malformed-duration")

    db = TestingSessionLocal()
    try:
        evidence = db.query(CertificationEvidence).filter(
            CertificationEvidence.id == record["evidence_id"]
        ).one()
        session = _linked_session(db, record["evidence_id"])
        report = dict(session.final_report or {})
        report["measured_duration_seconds"] = "not-a-number"
        report_without_hash = dict(report)
        report_without_hash.pop("report_sha256", None)
        report["report_sha256"] = canonical_hash(report_without_hash)
        session.final_report = report
        session.report_sha256 = report["report_sha256"]
        db.flush()

        reasons = shadow_evidence_provenance_reasons(
            db,
            evidence,
            expected_user_id=session.user_id,
            canonical_hash=canonical_hash,
        )
        assert "shadow_duration_mismatch" in reasons
        assert "shadow_duration_below_required_minimum" in reasons
    finally:
        db.rollback()
        db.close()


def test_system_scoped_shadow_claim_is_never_qualifying(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    user_id = _owner_id()
    metadata = {
        "full_stack_shadow_session": True,
        "session_id": 123456,
        "report_sha256": "3" * 64,
        "measured_elapsed_time": True,
        "final_submit_enabled": False,
        "final_submit_clicked": False,
    }
    payload = evidence_payload(
        evidence_type="shadow_run_4h",
        adapter=None,
        commit_sha=REVISION,
        environment="full-stack-shadow",
        status="passed",
        duration_seconds=4 * 60 * 60,
        source_reference="full-stack-shadow-session:123456:" + "3" * 64,
        evidence_metadata=metadata,
    )
    db = TestingSessionLocal()
    try:
        record = CertificationEvidence(
            evidence_key="system-shadow-provenance-test",
            evidence_type="shadow_run_4h",
            adapter=None,
            commit_sha=REVISION,
            environment="full-stack-shadow",
            status="passed",
            duration_seconds=4 * 60 * 60,
            source_reference=payload["source_reference"],
            payload_hash=canonical_hash(payload),
            evidence_metadata=metadata,
            recorded_by_user_id=None,
            review_status="verified",
        )
        db.add(record)
        db.flush()
        qualifying, reasons = evidence_is_qualifying(
            record,
            revision=REVISION,
            db=db,
            user_id=user_id,
        )
        assert qualifying is False
        assert "shadow_evidence_must_be_user_owned" in reasons
        assert "shadow_session_missing" in reasons
    finally:
        db.rollback()
        db.close()


def test_all_generic_shadow_recording_routes_fail_closed(monkeypatch, auth_client):
    _patch_revision(monkeypatch)
    for evidence_type, duration in (
        ("shadow_run_4h", 4 * 60 * 60),
        ("shadow_run_8h", 8 * 60 * 60),
        ("shadow_run_24h", 24 * 60 * 60),
    ):
        response = auth_client.post(
            "/api/certification/evidence",
            json={
                "evidence_type": evidence_type,
                "commit_sha": REVISION,
                "environment": "full-stack-shadow",
                "status": "passed",
                "duration_seconds": duration,
                "source_reference": f"manual:{evidence_type}",
                "evidence_metadata": {
                    "full_stack_shadow_session": True,
                    "session_id": 1,
                    "report_sha256": "4" * 64,
                    "measured_elapsed_time": True,
                    "final_submit_enabled": False,
                    "final_submit_clicked": False,
                },
            },
        )
        assert response.status_code == 422, response.text
