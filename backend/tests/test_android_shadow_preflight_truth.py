from __future__ import annotations

import pytest

from app.api import shadow_runs as shadow_api
from app.models.user import User


def _user(db_session) -> User:
    user = User(
        email="shadow-preflight-truth@example.test",
        hashed_password="test-hash",
        automation_settings={},
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _base_preflight() -> dict:
    return {
        "ok": True,
        "checks": {
            "target_supported": True,
            "candidate_revision_known": True,
            "real_submission_disabled": True,
        },
        "blockers": [],
        "candidate_revision": "a" * 40,
        "target_evidence_type": "shadow_run_4h",
        "requested_duration_seconds": 4 * 60 * 60,
        "expected_start_acknowledgment": "START FULL STACK SHADOW shadow_run_4h aaaaaaaaaaaa",
    }


def _ready_policy() -> dict:
    return {
        "ok": True,
        "checks": {
            "scheduler_policy_version_current": True,
            "scheduler_auto_search_enabled": True,
            "scheduler_auto_apply_enabled": True,
            "scheduler_dry_run_enabled": True,
            "autopilot_policy_currently_allowed": True,
            "quiet_hours_clear_for_requested_window": True,
            "daily_capacity_headroom": True,
            "weekly_capacity_headroom": True,
            "circuit_breaker_clear": True,
        },
        "blockers": [],
        "remaining_daily": 5,
        "remaining_weekly": 20,
    }


def test_android_preflight_surfaces_full_window_policy_blocker_before_qualification(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(shadow_api, "full_stack_shadow_preflight", lambda *_args, **_kwargs: _base_preflight())

    policy = _ready_policy()
    policy["ok"] = False
    policy["checks"]["quiet_hours_clear_for_requested_window"] = False
    policy["blockers"] = ["quiet_hours_clear_for_requested_window"]
    monkeypatch.setattr(shadow_api, "campaign_policy_readiness", lambda *_args, **_kwargs: policy)
    monkeypatch.setattr(
        shadow_api,
        "build_search_plan",
        lambda _user: {"ready": True, "reason_code": "search_plan_ready", "search_params": {}},
    )

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_4h",
    )

    assert result["ok"] is False
    assert result["expected_start_acknowledgment"] is None
    assert result["checks"]["qualification_quiet_hours_clear_for_requested_window"] is False
    assert "qualification_quiet_hours_clear_for_requested_window" in result["blockers"]


def test_android_preflight_surfaces_search_plan_blocker_before_qualification(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(shadow_api, "full_stack_shadow_preflight", lambda *_args, **_kwargs: _base_preflight())
    monkeypatch.setattr(shadow_api, "campaign_policy_readiness", lambda *_args, **_kwargs: _ready_policy())
    monkeypatch.setattr(
        shadow_api,
        "build_search_plan",
        lambda _user: {
            "ready": False,
            "reason_code": "search_location_missing",
            "reason": "missing",
            "search_params": None,
        },
    )

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_4h",
    )

    assert result["ok"] is False
    assert result["checks"]["qualification_search_plan_ready"] is False
    assert "qualification_search_location_missing" in result["blockers"]
    assert result["expected_start_acknowledgment"] is None


def test_android_preflight_reserves_canary_and_campaign_capacity(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(shadow_api, "full_stack_shadow_preflight", lambda *_args, **_kwargs: _base_preflight())
    observed = {}

    def fake_policy(_db, _user, *, requested_duration_seconds, required_remaining_applications):
        observed["duration"] = int(requested_duration_seconds)
        observed["remaining"] = int(required_remaining_applications)
        return _ready_policy()

    monkeypatch.setattr(shadow_api, "campaign_policy_readiness", fake_policy)
    monkeypatch.setattr(
        shadow_api,
        "build_search_plan",
        lambda _user: {"ready": True, "reason_code": "search_plan_ready", "search_params": {}},
    )

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_4h",
    )

    assert result["ok"] is True
    assert observed == {"duration": 4 * 60 * 60, "remaining": 2}
    assert result["qualification_preflight"]["required_remaining_applications"] == 2


def test_non_android_preflight_does_not_run_android_qualification_checks(
    db_session,
    monkeypatch,
):
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_MODE", raising=False)
    user = _user(db_session)
    base = _base_preflight()
    monkeypatch.setattr(shadow_api, "full_stack_shadow_preflight", lambda *_args, **_kwargs: base)
    monkeypatch.setattr(
        shadow_api,
        "campaign_policy_readiness",
        lambda *_args, **_kwargs: pytest.fail("Android policy readiness must not run"),
    )
    monkeypatch.setattr(
        shadow_api,
        "build_search_plan",
        lambda *_args, **_kwargs: pytest.fail("Android search readiness must not run"),
    )

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_4h",
    )

    assert result is base
    assert result["ok"] is True


def test_start_route_blocks_before_running_canary_when_visible_preflight_is_not_ready(
    auth_client,
    db_session,
    monkeypatch,
):
    authenticated = db_session.query(User).filter(User.email == "test@example.com").one()
    monkeypatch.setattr(
        shadow_api,
        "_runtime_identity_gate",
        lambda: {
            "required": True,
            "ok": True,
            "identity": {
                "deployment_attested": True,
                "revision": "a" * 40,
                "role": "api",
            },
        },
    )
    monkeypatch.setattr(
        shadow_api,
        "_shadow_start_preflight",
        lambda *_args, **_kwargs: {
            "ok": False,
            "checks": {"qualification_quiet_hours_clear_for_requested_window": False},
            "blockers": ["qualification_quiet_hours_clear_for_requested_window"],
            "expected_start_acknowledgment": None,
        },
    )
    qualification_calls = []
    monkeypatch.setattr(
        shadow_api,
        "_ensure_android_account_qualification",
        lambda **kwargs: qualification_calls.append(kwargs),
    )

    response = auth_client.post(
        "/api/shadow-runs",
        json={
            "target_evidence_type": "shadow_run_4h",
            "cycle_interval_seconds": 900,
            "acknowledgment": "anything",
        },
    )

    assert int(authenticated.id) > 0
    assert response.status_code == 409
    assert "qualification_quiet_hours_clear_for_requested_window" in response.text
    assert qualification_calls == []
