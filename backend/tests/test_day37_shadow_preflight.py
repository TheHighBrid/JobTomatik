from __future__ import annotations

import pytest

from app.api import shadow_runs as shadow_api
from app.models.user import User


REVISION = "7" * 40


def _user(db_session) -> User:
    user = User(
        email="day37-preflight@example.test",
        hashed_password="test-hash",
        automation_settings={},
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _base_preflight(target: str) -> dict:
    duration = {
        "shadow_run_4h": 4 * 60 * 60,
        "shadow_run_8h": 8 * 60 * 60,
        "shadow_run_24h": 24 * 60 * 60,
    }[target]
    return {
        "ok": True,
        "checks": {
            "target_supported": True,
            "candidate_revision_known": True,
            "real_submission_disabled": True,
            "global_autopilot_enabled": True,
            "global_kill_switch_clear": True,
            "scheduler_auto_search_enabled": True,
            "scheduler_auto_apply_enabled": True,
            "scheduler_dry_run_enabled": True,
        },
        "blockers": [],
        "candidate_revision": REVISION,
        "target_evidence_type": target,
        "requested_duration_seconds": duration,
        "expected_start_acknowledgment": (
            f"START FULL STACK SHADOW {target} {REVISION[:12]}"
        ),
    }


def _day37_admission(*, ok: bool) -> dict:
    checks = {
        "target_is_exact_8h": True,
        "candidate_revision_is_current_runtime": True,
        "verified_day36_predecessor": ok,
        "fresh_exact_runtime_acceptance": True,
        "runtime_acceptance_revision_matches_campaign": True,
        "campaign_policy_ready_for_8h": True,
        "real_application_submit_disabled": True,
        "real_followup_send_disabled": True,
        "lever_still_frozen_dry_run": True,
    }
    return {
        "ok": ok,
        "target_evidence_type": "shadow_run_8h",
        "requested_duration_seconds": 8 * 60 * 60,
        "candidate_revision": REVISION,
        "current_revision": REVISION,
        "checks": checks,
        "blockers": [] if ok else ["verified_day36_predecessor", "day36:verified_day36_predecessor_missing"],
        "predecessor": {
            "ok": ok,
            "blockers": [] if ok else ["verified_day36_predecessor_missing"],
            "predecessor": (
                {
                    "evidence_id": 36,
                    "session_id": 360,
                    "candidate_revision": "6" * 40,
                }
                if ok
                else None
            ),
        },
        "runtime_acceptance": {
            "ok": True,
            "blockers": [],
            "revision": REVISION,
            "runtime_fingerprint_sha256": "a" * 64,
        },
        "policy": {"ok": True, "blockers": [], "policy_profile": "shadow_test"},
        "lever": {
            "name": "lever",
            "version": "1.1.0",
            "maturity": "dry_run",
            "autonomous_submission_allowed": False,
        },
        "safety": {
            "submission_authorized": False,
            "outreach_authorized": False,
            "promotion_authorized": False,
        },
    }


def test_android_eight_hour_preflight_surfaces_day37_predecessor_blocker(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(
        shadow_api,
        "full_stack_shadow_preflight",
        lambda *_args, **_kwargs: _base_preflight("shadow_run_8h"),
    )
    monkeypatch.setattr(
        shadow_api,
        "day37_android_launch_admission",
        lambda *_args, **_kwargs: _day37_admission(ok=False),
    )

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_8h",
    )

    assert result["ok"] is False
    assert result["checks"]["day37_verified_day36_predecessor"] is False
    assert "day37_verified_day36_predecessor" in result["blockers"]
    assert result["expected_start_acknowledgment"] is None
    assert result["day37_admission"]["predecessor"]["ok"] is False
    assert "day36:verified_day36_predecessor_missing" in result["day37_admission"]["blockers"]


def test_android_eight_hour_preflight_preserves_ack_only_when_day37_is_ready(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(
        shadow_api,
        "full_stack_shadow_preflight",
        lambda *_args, **_kwargs: _base_preflight("shadow_run_8h"),
    )
    monkeypatch.setattr(
        shadow_api,
        "day37_android_launch_admission",
        lambda *_args, **_kwargs: _day37_admission(ok=True),
    )

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_8h",
    )

    assert result["ok"] is True
    assert result["blockers"] == []
    assert all(
        result["checks"][f"day37_{name}"] is True
        for name in _day37_admission(ok=True)["checks"]
    )
    assert result["expected_start_acknowledgment"] == (
        f"START FULL STACK SHADOW shadow_run_8h {REVISION[:12]}"
    )
    assert result["day37_admission"]["safety"] == {
        "submission_authorized": False,
        "outreach_authorized": False,
        "promotion_authorized": False,
    }


def test_android_twenty_four_hour_preflight_stays_explicitly_locked(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(
        shadow_api,
        "full_stack_shadow_preflight",
        lambda *_args, **_kwargs: _base_preflight("shadow_run_24h"),
    )
    monkeypatch.setattr(
        shadow_api,
        "day37_android_launch_admission",
        lambda *_args, **_kwargs: pytest.fail("Day 37 admission must not unlock the Day 38 stage"),
    )

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_24h",
    )

    assert result["ok"] is False
    assert result["checks"]["day38_24h_stage_unlocked"] is False
    assert result["blockers"] == ["day38_24h_stage_unlocked"]
    assert result["expected_start_acknowledgment"] is None
    assert result["stage_gate"]["stage"] == "day38"
    assert result["stage_gate"]["submission_authorized"] is False
    assert result["stage_gate"]["outreach_authorized"] is False


def test_non_android_eight_hour_preflight_does_not_require_physical_day37_gate(
    db_session,
    monkeypatch,
):
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_MODE", raising=False)
    user = _user(db_session)
    base = _base_preflight("shadow_run_8h")
    monkeypatch.setattr(
        shadow_api,
        "full_stack_shadow_preflight",
        lambda *_args, **_kwargs: base,
    )
    monkeypatch.setattr(
        shadow_api,
        "day37_android_launch_admission",
        lambda *_args, **_kwargs: pytest.fail("Physical Day 37 admission must stay Android-specific"),
    )

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_8h",
    )

    assert result is base
    assert result["ok"] is True
    assert result["expected_start_acknowledgment"]
