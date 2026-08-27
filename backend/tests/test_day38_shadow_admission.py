from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.certification import CertificationEvidence, ShadowRunSession
from app.models.user import User
from app.services import day38_shadow_admission
from app.services.day38_shadow_admission import (
    DAY38_SECONDS,
    day38_android_launch_admission,
    day38_predecessor_admission,
)


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
DAY37_REVISION = "7" * 40
DAY38_REVISION = "8" * 40


def _user(db_session) -> User:
    user = User(
        email="day38-admission@example.test",
        hashed_password="test-hash",
        automation_settings={},
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _reviewed_day37(db_session, user: User) -> tuple[ShadowRunSession, CertificationEvidence]:
    session = ShadowRunSession(
        user_id=user.id,
        candidate_revision=DAY37_REVISION,
        target_evidence_type="shadow_run_8h",
        requested_duration_seconds=8 * 60 * 60,
        cycle_interval_seconds=900,
        status="completed",
        started_at=NOW - timedelta(hours=9),
        expected_end_at=NOW - timedelta(hours=1),
        completed_at=NOW - timedelta(minutes=50),
        final_submit_allowed=False,
        stop_requested=False,
        final_report={"qualification_eligible": True},
        report_sha256="a" * 64,
    )
    db_session.add(session)
    db_session.flush()

    evidence = CertificationEvidence(
        evidence_key=f"day38-test-{session.id}",
        evidence_type="shadow_run_8h",
        adapter=None,
        commit_sha=DAY37_REVISION,
        environment="full-stack-shadow",
        status="passed",
        duration_seconds=8 * 60 * 60,
        source_reference=f"full-stack-shadow-session:{session.id}:{session.report_sha256}",
        payload_hash="b" * 64,
        evidence_metadata={"full_stack_shadow_session": True, "session_id": session.id},
        recorded_by_user_id=user.id,
        review_status="verified",
        reviewed_by_user_id=user.id,
        reviewed_at=NOW - timedelta(minutes=30),
        review_reference="review:day37-strict-endurance",
    )
    db_session.add(evidence)
    db_session.flush()
    session.certification_evidence_id = evidence.id
    db_session.flush()
    return session, evidence


def _strict_day37_report(session: ShadowRunSession, *, passed: bool) -> dict:
    return {
        "passed": passed,
        "day38_entry_eligible": passed,
        "candidate_revision": session.candidate_revision,
        "report_sha256": "c" * 64,
        "retained_phase11_report_sha256": session.report_sha256,
        "persisted_elapsed_seconds": 8 * 60 * 60 + 60,
    }


def _patch_predecessor_integrity(monkeypatch, session: ShadowRunSession, *, strict_passed: bool) -> None:
    monkeypatch.setattr(day38_shadow_admission, "evidence_integrity_ok", lambda *_args: True)
    monkeypatch.setattr(
        day38_shadow_admission,
        "shadow_evidence_provenance_reasons",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        day38_shadow_admission,
        "build_day37_shadow_endurance_report",
        lambda *_args, **_kwargs: _strict_day37_report(session, passed=strict_passed),
    )


def test_missing_verified_day37_predecessor_blocks_day38(db_session):
    user = _user(db_session)

    result = day38_predecessor_admission(db_session, user_id=user.id, now=NOW)

    assert result["ok"] is False
    assert result["predecessor"] is None
    assert "verified_day37_predecessor_missing" in result["blockers"]


def test_reviewed_strictly_passing_day37_predecessor_is_accepted(
    db_session,
    monkeypatch,
):
    user = _user(db_session)
    session, evidence = _reviewed_day37(db_session, user)
    _patch_predecessor_integrity(monkeypatch, session, strict_passed=True)

    result = day38_predecessor_admission(db_session, user_id=user.id, now=NOW)

    assert result["ok"] is True
    assert result["blockers"] == []
    assert result["predecessor"]["evidence_id"] == evidence.id
    assert result["predecessor"]["session_id"] == session.id
    assert result["predecessor"]["candidate_revision"] == DAY37_REVISION
    assert result["predecessor"]["review_status"] == "verified"


def test_ordinary_passed_evidence_cannot_bypass_failed_strict_day37_certifier(
    db_session,
    monkeypatch,
):
    user = _user(db_session)
    session, _evidence = _reviewed_day37(db_session, user)
    _patch_predecessor_integrity(monkeypatch, session, strict_passed=False)

    result = day38_predecessor_admission(db_session, user_id=user.id, now=NOW)

    assert result["ok"] is False
    assert "predecessor_day37_certifier_not_passed" in result["blockers"]
    assert "predecessor_day38_entry_not_eligible" in result["blockers"]


def _patch_launch_dependencies(monkeypatch, *, runtime_revision: str = DAY38_REVISION) -> None:
    monkeypatch.setattr(
        day38_shadow_admission,
        "day38_predecessor_admission",
        lambda *_args, **_kwargs: {
            "ok": True,
            "blockers": [],
            "predecessor": {
                "candidate_revision": DAY37_REVISION,
                "evidence_id": 37,
                "session_id": 370,
            },
            "attempts": [],
        },
    )
    monkeypatch.setattr(
        day38_shadow_admission,
        "runtime_acceptance_status",
        lambda **_kwargs: {
            "ok": True,
            "blockers": [],
            "revision": runtime_revision,
            "runtime_fingerprint": {"sha256": "d" * 64},
        },
    )
    monkeypatch.setattr(
        day38_shadow_admission,
        "campaign_policy_readiness",
        lambda *_args, **_kwargs: {
            "ok": True,
            "blockers": [],
            "policy_profile": "shadow_test",
            "production_quiet_hours_collision_at": NOW.isoformat(),
        },
    )
    monkeypatch.setattr(day38_shadow_admission, "current_revision", lambda: DAY38_REVISION)
    monkeypatch.setattr(
        day38_shadow_admission,
        "get_settings",
        lambda: SimpleNamespace(
            allow_real_application_submit=False,
            allow_real_followup_send=False,
        ),
    )
    monkeypatch.setattr(
        day38_shadow_admission,
        "_lever_state",
        lambda: {
            "name": "lever",
            "version": "1.1.0",
            "maturity": "dry_run",
            "autonomous_submission_allowed": False,
        },
    )


def test_day38_launch_accepts_older_day37_revision_but_requires_current_runtime(
    db_session,
    monkeypatch,
):
    user = _user(db_session)
    _patch_launch_dependencies(monkeypatch)

    result = day38_android_launch_admission(
        db_session,
        user,
        candidate_revision=DAY38_REVISION,
        requested_duration_seconds=DAY38_SECONDS,
        now=NOW,
    )

    assert result["ok"] is True
    assert result["predecessor"]["predecessor"]["candidate_revision"] == DAY37_REVISION
    assert result["candidate_revision"] == DAY38_REVISION
    assert result["checks"]["target_is_exact_24h"] is True
    assert result["checks"]["verified_day37_predecessor"] is True
    assert result["safety"] == {
        "submission_authorized": False,
        "outreach_authorized": False,
        "promotion_authorized": False,
    }


def test_day38_launch_fails_closed_on_wrong_duration_or_runtime_revision(
    db_session,
    monkeypatch,
):
    user = _user(db_session)
    _patch_launch_dependencies(monkeypatch, runtime_revision="9" * 40)

    result = day38_android_launch_admission(
        db_session,
        user,
        candidate_revision=DAY38_REVISION,
        requested_duration_seconds=8 * 60 * 60,
        now=NOW,
    )

    assert result["ok"] is False
    assert "target_is_exact_24h" in result["blockers"]
    assert "runtime_acceptance_revision_matches_campaign" in result["blockers"]
