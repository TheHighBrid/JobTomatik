from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api import shadow_runs as shadow_api
from app.models.application import Application
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services import scheduler_policy, shadow_qualification
from app.services.operations_policy import AutomationDecision
from app.services.scheduler_policy import SCHEDULER_POLICY_VERSION


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
            "shadow_eligible_public_ats_target_configured": True,
        },
        "blockers": [],
        "remaining_daily": 5,
        "remaining_weekly": 20,
    }


def _new_canary_required() -> dict:
    return {"ok": False, "blockers": ["receipt_present"], "receipt": {}}


def _fresh_canary_reusable() -> dict:
    return {"ok": True, "blockers": [], "receipt": {"status": "pass"}}


def _install_ready_search(monkeypatch) -> None:
    monkeypatch.setattr(
        shadow_api,
        "build_search_plan",
        lambda _user: {"ready": True, "reason_code": "search_plan_ready", "search_params": {}},
    )


def test_android_preflight_surfaces_full_window_policy_blocker_before_qualification(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(shadow_api, "full_stack_shadow_preflight", lambda *_args, **_kwargs: _base_preflight())
    monkeypatch.setattr(shadow_api, "canary_receipt_status", lambda *_args, **_kwargs: _new_canary_required())

    policy = _ready_policy()
    policy["ok"] = False
    policy["checks"]["quiet_hours_clear_for_requested_window"] = False
    policy["blockers"] = ["quiet_hours_clear_for_requested_window"]
    monkeypatch.setattr(shadow_api, "campaign_policy_readiness", lambda *_args, **_kwargs: policy)
    _install_ready_search(monkeypatch)

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
    monkeypatch.setattr(shadow_api, "canary_receipt_status", lambda *_args, **_kwargs: _new_canary_required())
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


def test_android_preflight_surfaces_missing_shadow_eligible_public_ats_target(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(shadow_api, "full_stack_shadow_preflight", lambda *_args, **_kwargs: _base_preflight())
    monkeypatch.setattr(shadow_api, "canary_receipt_status", lambda *_args, **_kwargs: _new_canary_required())
    policy = _ready_policy()
    policy["ok"] = False
    policy["checks"]["shadow_eligible_public_ats_target_configured"] = False
    policy["blockers"] = ["shadow_eligible_public_ats_target_configured"]
    monkeypatch.setattr(shadow_api, "campaign_policy_readiness", lambda *_args, **_kwargs: policy)
    _install_ready_search(monkeypatch)

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_4h",
    )

    assert result["ok"] is False
    assert result["expected_start_acknowledgment"] is None
    assert result["checks"]["qualification_shadow_eligible_public_ats_target_configured"] is False
    assert "qualification_shadow_eligible_public_ats_target_configured" in result["blockers"]


def test_android_preflight_reserves_canary_and_campaign_capacity_when_canary_is_needed(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(shadow_api, "full_stack_shadow_preflight", lambda *_args, **_kwargs: _base_preflight())
    monkeypatch.setattr(shadow_api, "canary_receipt_status", lambda *_args, **_kwargs: _new_canary_required())
    observed = {}

    def fake_policy(_db, _user, *, requested_duration_seconds, required_remaining_applications):
        observed["duration"] = int(requested_duration_seconds)
        observed["remaining"] = int(required_remaining_applications)
        return _ready_policy()

    monkeypatch.setattr(shadow_api, "campaign_policy_readiness", fake_policy)
    _install_ready_search(monkeypatch)

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_4h",
    )

    assert result["ok"] is True
    assert observed == {"duration": 4 * 60 * 60, "remaining": 2}
    assert result["qualification_preflight"]["qualification_receipt_reusable"] is False
    assert result["qualification_preflight"]["required_remaining_applications"] == 2


def test_android_preflight_requires_only_campaign_capacity_when_canary_is_reusable(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(shadow_api, "full_stack_shadow_preflight", lambda *_args, **_kwargs: _base_preflight())
    monkeypatch.setattr(shadow_api, "canary_receipt_status", lambda *_args, **_kwargs: _fresh_canary_reusable())
    observed = {}

    def fake_policy(_db, _user, *, requested_duration_seconds, required_remaining_applications):
        observed["duration"] = int(requested_duration_seconds)
        observed["remaining"] = int(required_remaining_applications)
        return _ready_policy()

    monkeypatch.setattr(shadow_api, "campaign_policy_readiness", fake_policy)
    _install_ready_search(monkeypatch)

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_4h",
    )

    assert result["ok"] is True
    assert observed == {"duration": 4 * 60 * 60, "remaining": 1}
    assert result["qualification_preflight"]["qualification_receipt_reusable"] is True
    assert result["qualification_preflight"]["required_remaining_applications"] == 1


def test_android_preflight_treats_runtime_only_staleness_as_reusable_after_refresh(
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    user = _user(db_session)
    monkeypatch.setattr(shadow_api, "full_stack_shadow_preflight", lambda *_args, **_kwargs: _base_preflight())
    monkeypatch.setattr(
        shadow_api,
        "canary_receipt_status",
        lambda *_args, **_kwargs: {
            "ok": False,
            "blockers": ["runtime_acceptance_ready"],
            "receipt": {"status": "pass"},
        },
    )
    observed = {}

    def fake_policy(_db, _user, *, requested_duration_seconds, required_remaining_applications):
        observed["remaining"] = int(required_remaining_applications)
        return _ready_policy()

    monkeypatch.setattr(shadow_api, "campaign_policy_readiness", fake_policy)
    _install_ready_search(monkeypatch)

    result = shadow_api._shadow_start_preflight(
        db_session,
        user,
        target_evidence_type="shadow_run_4h",
    )

    assert result["ok"] is True
    assert observed["remaining"] == 1
    assert result["qualification_preflight"]["qualification_receipt_reusable"] is True
    assert result["qualification_preflight"]["qualification_receipt_blockers"] == ["runtime_acceptance_ready"]


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
        "canary_receipt_status",
        lambda *_args, **_kwargs: pytest.fail("Android qualification receipt must not be inspected"),
    )
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


def test_policy_readiness_counts_real_capacity_even_when_quiet_hours_short_circuit_policy(
    db_session,
    monkeypatch,
):
    user = _user(db_session)
    current = datetime(2026, 8, 13, 5, 30, 0)
    user.automation_settings = {
        "scheduler_policy_version": SCHEDULER_POLICY_VERSION,
        "auto_search_enabled": True,
        "auto_apply_enabled": True,
        "dry_run_mode": True,
        "auto_apply_daily_limit": 5,
        "auto_apply_weekly_limit": 20,
        "quiet_hours_start_utc": 0,
        "quiet_hours_end_utc": 6,
    }
    user.job_preferences = {
        "ats_targets": [
            {"provider": "lever", "identifier": "example-bank", "company": "Example Bank"}
        ]
    }
    for index in range(2):
        job = Job(
            external_id=f"capacity-{index}",
            title="Risk analyst",
            company=f"Capacity Co {index}",
            source=JobSource.manual,
            status=JobStatus.approved,
            relevance_score=0.9,
            url=f"https://example.test/{index}",
        )
        db_session.add(job)
        db_session.flush()
        db_session.add(
            Application(
                user_id=user.id,
                job_id=job.id,
                created_at=current - timedelta(hours=index + 1),
            )
        )
    db_session.commit()

    monkeypatch.setattr(
        shadow_qualification,
        "get_operations_settings",
        lambda: SimpleNamespace(
            default_daily_cap=5,
            default_weekly_cap=20,
            quiet_hours_start_utc=0,
            quiet_hours_end_utc=6,
        ),
    )
    monkeypatch.setattr(
        shadow_qualification,
        "scheduler_settings",
        lambda _user: {
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": True,
        },
    )
    monkeypatch.setattr(
        shadow_qualification,
        "evaluate_autopilot_policy",
        lambda *_args, **_kwargs: AutomationDecision(
            False,
            "quiet_hours",
            "quiet",
            {"start_hour_utc": 0, "end_hour_utc": 6, "current_hour_utc": 5},
        ),
    )
    monkeypatch.setattr(
        shadow_qualification,
        "live_platform_maturities",
        lambda: {"lever": "dry_run"},
    )

    result = shadow_qualification.campaign_policy_readiness(
        db_session,
        user,
        requested_duration_seconds=4 * 60 * 60,
        required_remaining_applications=2,
        now=current,
    )

    assert result["checks"]["autopilot_policy_currently_allowed"] is False
    assert result["checks"]["quiet_hours_clear_for_requested_window"] is False
    assert result["daily_count"] == 2
    assert result["weekly_count"] == 2
    assert result["remaining_daily"] == 3
    assert result["remaining_weekly"] == 18
    assert result["checks"]["daily_capacity_headroom"] is True
    assert result["checks"]["weekly_capacity_headroom"] is True


def test_policy_readiness_requires_explicit_shadow_eligible_public_ats_target(
    db_session,
    monkeypatch,
):
    user = _user(db_session)
    user.automation_settings = {
        "scheduler_policy_version": SCHEDULER_POLICY_VERSION,
        "auto_search_enabled": True,
        "auto_apply_enabled": True,
        "dry_run_mode": True,
        "quiet_hours_start_utc": 0,
        "quiet_hours_end_utc": 0,
    }
    db_session.commit()

    monkeypatch.setattr(
        shadow_qualification,
        "get_operations_settings",
        lambda: SimpleNamespace(
            default_daily_cap=5,
            default_weekly_cap=20,
            quiet_hours_start_utc=0,
            quiet_hours_end_utc=0,
        ),
    )
    monkeypatch.setattr(
        shadow_qualification,
        "scheduler_settings",
        lambda _user: {
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": True,
        },
    )
    monkeypatch.setattr(
        shadow_qualification,
        "evaluate_autopilot_policy",
        lambda *_args, **_kwargs: AutomationDecision(True, "autopilot_allowed", "allowed", {}),
    )
    monkeypatch.setattr(
        shadow_qualification,
        "live_platform_maturities",
        lambda: {"lever": "dry_run", "greenhouse": "detect_only"},
    )

    missing = shadow_qualification.campaign_policy_readiness(
        db_session,
        user,
        requested_duration_seconds=4 * 60 * 60,
    )
    assert missing["checks"]["shadow_eligible_public_ats_target_configured"] is False
    assert "shadow_eligible_public_ats_target_configured" in missing["blockers"]

    user.job_preferences = {
        "ats_targets": [
            {"provider": "lever", "identifier": "example-bank", "company": "Example Bank"},
            {"provider": "greenhouse", "identifier": "detect-only", "company": "Detect Only"},
        ]
    }
    db_session.commit()
    ready = shadow_qualification.campaign_policy_readiness(
        db_session,
        user,
        requested_duration_seconds=4 * 60 * 60,
    )
    assert ready["checks"]["shadow_eligible_public_ats_target_configured"] is True
    assert ready["eligible_shadow_ats_targets"] == [
        {
            "provider": "lever",
            "identifier": "example-bank",
            "company": "Example Bank",
            "maturity": "dry_run",
        }
    ]


def test_scheduler_candidate_scan_reaches_eligible_job_beyond_old_first_fifty(
    db_session,
    monkeypatch,
):
    user = _user(db_session)
    monkeypatch.setattr(
        scheduler_policy,
        "scheduler_settings",
        lambda _user: {"auto_apply_min_score": 0.65},
    )

    for index in range(60):
        db_session.add(
            Job(
                external_id=f"blocked-{index}",
                title="Blocked role",
                company=f"Blocked Co {index}",
                source=JobSource.manual,
                status=JobStatus.queued,
                relevance_score=0.99,
                url=f"https://example.test/blocked/{index}",
            )
        )
    db_session.add(
        Job(
            external_id="eligible",
            title="Eligible Lever role",
            company="Eligible Co",
            source=JobSource.lever,
            status=JobStatus.queued,
            relevance_score=0.70,
            url="https://jobs.lever.co/eligible/role",
        )
    )
    db_session.commit()

    def fake_job_policy(_db, _user, job, now=None):
        allowed = job.external_id == "eligible"
        return AutomationDecision(
            allowed,
            "shadow_dry_run_maturity_exception" if allowed else "platform_not_certified",
            "allowed" if allowed else "blocked",
            {},
        )

    monkeypatch.setattr(scheduler_policy, "evaluate_unattended_job_policy", fake_job_policy)

    ranked = scheduler_policy.rank_scheduler_candidates(db_session, user, limit=4)

    assert ranked
    assert ranked[0]["job"].external_id == "eligible"
    assert ranked[0]["decision"]["allowed"] is True
