from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.certification import (
    CertificationEvidence,
    ShadowRunSession,
    _require_android_shadow_admission,
)
from app.models.user import User
from app.services import day37_shadow_admission
from app.services.certification_scale import canonical_hash, evidence_key_for, evidence_payload
from app.services.day37_shadow_admission import (
    DAY37_SECONDS,
    day37_android_launch_admission,
    day37_predecessor_admission,
)
from tests.test_day36_shadow_endurance import REVISION, _application, _session, _user


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _make_day36_report_provenance_valid(session: ShadowRunSession) -> None:
    """Add the Phase 12 reconciliation invariant and rebind the retained hash."""

    report = dict(session.final_report or {})
    reconciliation = dict(report.get("reconciliation") or {})
    reconciliation["reconciled"] = True
    report["reconciliation"] = reconciliation
    payload = dict(report)
    payload.pop("report_sha256", None)
    report["report_sha256"] = canonical_hash(payload)
    session.final_report = report
    session.report_sha256 = report["report_sha256"]


def _record_day36_evidence(
    db,
    user: User,
    session: ShadowRunSession,
    *,
    review_status: str = "verified",
    duration_seconds: int | None = None,
    payload_hash_override: str | None = None,
) -> CertificationEvidence:
    report = dict(session.final_report or {})
    duration = int(
        duration_seconds
        if duration_seconds is not None
        else float(report.get("measured_duration_seconds") or 0)
    )
    metadata = {
        "full_stack_shadow_session": True,
        "session_id": session.id,
        "report_sha256": session.report_sha256,
        "measured_elapsed_time": True,
        "final_submit_enabled": False,
        "final_submit_clicked": False,
        "real_submission_remained_disabled": True,
        "qualification_eligible": True,
        "cycles_completed": int(session.cycles_completed or 0),
        "cycles_failed": int(session.cycles_failed or 0),
        "applications_created": int(session.applications_created or 0),
        "human_boundaries": int(session.human_boundaries or 0),
        "reconciled": bool((report.get("reconciliation") or {}).get("reconciled")),
        "submission_authorized": False,
        "outreach_authorized": False,
    }
    payload = evidence_payload(
        evidence_type="shadow_run_4h",
        adapter=None,
        commit_sha=session.candidate_revision,
        environment="full-stack-shadow",
        status="passed",
        duration_seconds=duration,
        source_reference=f"full-stack-shadow-session:{session.id}:{session.report_sha256}",
        evidence_metadata=metadata,
    )
    record = CertificationEvidence(
        evidence_key=evidence_key_for(payload, owner_user_id=user.id),
        evidence_type="shadow_run_4h",
        adapter=None,
        commit_sha=session.candidate_revision,
        environment="full-stack-shadow",
        status="passed",
        duration_seconds=duration,
        source_reference=payload["source_reference"],
        payload_hash=payload_hash_override or canonical_hash(payload),
        evidence_metadata=metadata,
        recorded_by_user_id=user.id,
        review_status=review_status,
        reviewed_by_user_id=(user.id if review_status == "verified" else None),
        reviewed_at=(NOW if review_status == "verified" else None),
        review_reference=("day37-test-review" if review_status == "verified" else None),
        created_at=NOW,
    )
    db.add(record)
    db.flush()
    session.certification_evidence_id = record.id
    db.flush()
    return record


def _valid_predecessor(db):
    user = _user(db)
    application = _application(db, user)
    session = _session(db, user, application)
    _make_day36_report_provenance_valid(session)
    db.flush()
    record = _record_day36_evidence(db, user, session)
    return user, session, record


def test_valid_day36_predecessor_is_accepted_without_current_sha_equality(db_session):
    user, session, record = _valid_predecessor(db_session)

    admission = day37_predecessor_admission(
        db_session,
        user_id=user.id,
        now=NOW,
    )

    assert admission["ok"] is True
    assert admission["blockers"] == []
    assert admission["predecessor"]["evidence_id"] == record.id
    assert admission["predecessor"]["session_id"] == session.id
    assert admission["predecessor"]["candidate_revision"] == REVISION
    # The stage-specific gate validates the predecessor against its own retained SHA.
    # It deliberately does not require REVISION to equal the Day 37 current checkout.


def test_missing_or_unreviewed_day36_evidence_blocks(db_session):
    user = _user(db_session)
    missing = day37_predecessor_admission(db_session, user_id=user.id, now=NOW)
    assert missing["ok"] is False
    assert "verified_day36_predecessor_missing" in missing["blockers"]

    application = _application(db_session, user)
    session = _session(db_session, user, application)
    _record_day36_evidence(db_session, user, session, review_status="unreviewed")
    unreviewed = day37_predecessor_admission(db_session, user_id=user.id, now=NOW)
    assert unreviewed["ok"] is False
    assert "predecessor_not_independently_verified" in unreviewed["blockers"]


def test_tampered_day36_payload_blocks_even_when_reviewed(db_session):
    user, _session_row, record = _valid_predecessor(db_session)
    record.payload_hash = "0" * 64
    db_session.flush()

    admission = day37_predecessor_admission(db_session, user_id=user.id, now=NOW)

    assert admission["ok"] is False
    assert "predecessor_payload_hash_mismatch" in admission["blockers"]


def test_wrong_account_cannot_reuse_another_users_day36_predecessor(db_session):
    owner, _session_row, _record = _valid_predecessor(db_session)
    other = User(
        email="day37-other@example.com",
        hashed_password="hash",
        full_name="Day 37 Other",
        profile_data={},
        job_preferences={},
        automation_settings={},
        is_active=True,
    )
    db_session.add(other)
    db_session.flush()

    admission = day37_predecessor_admission(db_session, user_id=other.id, now=NOW)

    assert admission["ok"] is False
    assert admission["predecessor"] is None
    assert owner.id != other.id


def test_newer_junk_row_does_not_eclipse_older_valid_predecessor(db_session):
    user, session, valid = _valid_predecessor(db_session)
    junk_payload = evidence_payload(
        evidence_type="shadow_run_4h",
        adapter=None,
        commit_sha="9" * 40,
        environment="full-stack-shadow",
        status="passed",
        duration_seconds=4 * 60 * 60,
        source_reference="full-stack-shadow-session:999:junk",
        evidence_metadata={"full_stack_shadow_session": True, "session_id": 999},
    )
    junk = CertificationEvidence(
        evidence_key=evidence_key_for(junk_payload, owner_user_id=user.id),
        evidence_type="shadow_run_4h",
        adapter=None,
        commit_sha="9" * 40,
        environment="full-stack-shadow",
        status="passed",
        duration_seconds=4 * 60 * 60,
        source_reference=junk_payload["source_reference"],
        payload_hash=canonical_hash(junk_payload),
        evidence_metadata=junk_payload["evidence_metadata"],
        recorded_by_user_id=user.id,
        review_status="unreviewed",
        created_at=NOW + timedelta(minutes=1),
    )
    db_session.add(junk)
    db_session.flush()

    admission = day37_predecessor_admission(db_session, user_id=user.id, now=NOW)

    assert admission["ok"] is True
    assert admission["predecessor"]["evidence_id"] == valid.id
    assert admission["predecessor"]["session_id"] == session.id
    assert admission["attempts"][0]["evidence_id"] == junk.id
    assert "predecessor_not_independently_verified" in admission["attempts"][0]["reasons"]


def test_day37_launch_accepts_older_valid_predecessor_but_requires_current_runtime(monkeypatch, db_session):
    user = _user(db_session)
    current_revision = "7" * 40
    monkeypatch.setattr(
        day37_shadow_admission,
        "day37_predecessor_admission",
        lambda *_args, **_kwargs: {
            "ok": True,
            "blockers": [],
            "predecessor": {"candidate_revision": REVISION, "evidence_id": 1, "session_id": 1},
            "attempts": [],
        },
    )
    monkeypatch.setattr(
        day37_shadow_admission,
        "runtime_acceptance_status",
        lambda **_kwargs: {
            "ok": True,
            "blockers": [],
            "revision": current_revision,
            "runtime_fingerprint": {"sha256": "a" * 64},
        },
    )
    monkeypatch.setattr(
        day37_shadow_admission,
        "campaign_policy_readiness",
        lambda *_args, **_kwargs: {"ok": True, "blockers": [], "policy_profile": "shadow_test"},
    )
    monkeypatch.setattr(day37_shadow_admission, "current_revision", lambda: current_revision)
    monkeypatch.setattr(
        day37_shadow_admission,
        "get_settings",
        lambda: SimpleNamespace(
            allow_real_application_submit=False,
            allow_real_followup_send=False,
        ),
    )
    monkeypatch.setattr(
        day37_shadow_admission,
        "_lever_state",
        lambda: {
            "name": "lever",
            "version": "1.1.0",
            "maturity": "dry_run",
            "autonomous_submission_allowed": False,
        },
    )

    admission = day37_android_launch_admission(
        db_session,
        user,
        candidate_revision=current_revision,
        requested_duration_seconds=DAY37_SECONDS,
        now=NOW,
    )

    assert admission["ok"] is True
    assert admission["predecessor"]["predecessor"]["candidate_revision"] == REVISION
    assert admission["candidate_revision"] == current_revision
    assert admission["safety"] == {
        "submission_authorized": False,
        "outreach_authorized": False,
        "promotion_authorized": False,
    }


def test_day37_launch_fails_closed_on_wrong_duration_or_runtime_revision(monkeypatch, db_session):
    user = _user(db_session)
    current_revision = "7" * 40
    monkeypatch.setattr(
        day37_shadow_admission,
        "day37_predecessor_admission",
        lambda *_args, **_kwargs: {"ok": True, "blockers": [], "predecessor": {}, "attempts": []},
    )
    monkeypatch.setattr(
        day37_shadow_admission,
        "runtime_acceptance_status",
        lambda **_kwargs: {
            "ok": True,
            "blockers": [],
            "revision": "8" * 40,
            "runtime_fingerprint": {"sha256": "a" * 64},
        },
    )
    monkeypatch.setattr(
        day37_shadow_admission,
        "campaign_policy_readiness",
        lambda *_args, **_kwargs: {"ok": True, "blockers": [], "policy_profile": "shadow_test"},
    )
    monkeypatch.setattr(day37_shadow_admission, "current_revision", lambda: current_revision)
    monkeypatch.setattr(
        day37_shadow_admission,
        "get_settings",
        lambda: SimpleNamespace(
            allow_real_application_submit=False,
            allow_real_followup_send=False,
        ),
    )
    monkeypatch.setattr(
        day37_shadow_admission,
        "_lever_state",
        lambda: {
            "name": "lever",
            "version": "1.1.0",
            "maturity": "dry_run",
            "autonomous_submission_allowed": False,
        },
    )

    admission = day37_android_launch_admission(
        db_session,
        user,
        candidate_revision=current_revision,
        requested_duration_seconds=4 * 60 * 60,
        now=NOW,
    )

    assert admission["ok"] is False
    assert "target_is_exact_8h" in admission["blockers"]
    assert "runtime_acceptance_revision_matches_campaign" in admission["blockers"]


def test_android_24h_requires_fresh_runtime_acceptance_after_day38_unlock(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    target = ShadowRunSession(
        user_id=1,
        candidate_revision="7" * 40,
        target_evidence_type="shadow_run_24h",
        requested_duration_seconds=24 * 60 * 60,
        cycle_interval_seconds=900,
        status="scheduled",
        started_at=NOW,
        expected_end_at=NOW + timedelta(hours=24),
        final_submit_allowed=False,
        stop_requested=False,
    )

    # Day 38 no longer uses the old unconditional lock. It still fails closed at the
    # ORM boundary unless a fresh exact-runtime acceptance receipt exists.
    with pytest.raises(ValueError, match="requires fresh exact-runtime acceptance"):
        _require_android_shadow_admission(target)
