from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import config
from app.models.certification import ShadowRunSession
from app.models.user import User
from app.services import operations_policy, runtime_acceptance, shadow_qualification
from app.services.operations_settings import OperationsSettings
from app.services.scheduler_policy import SCHEDULER_POLICY_VERSION


REVISION = "a" * 40


def _operations() -> OperationsSettings:
    return OperationsSettings(
        global_kill_switch=False,
        autopilot_enabled=True,
        default_daily_cap=5,
        default_weekly_cap=20,
        quiet_hours_start_utc=0,
        quiet_hours_end_utc=0,
        failure_threshold=3,
        failure_window_minutes=60,
        circuit_breaker_minutes=120,
        stale_attempt_minutes=30,
        disabled_platforms="",
    )


def _user(db_session, *, policy_version: str = SCHEDULER_POLICY_VERSION) -> User:
    user = User(
        email=f"android-shadow-launch-{policy_version}@example.test",
        hashed_password="test-hash",
        automation_settings={
            "scheduler_policy_version": policy_version,
            "auto_search_enabled": True,
            "auto_apply_enabled": True,
            "dry_run_mode": True,
            "auto_apply_min_score": 0.65,
            "auto_apply_daily_limit": 5,
            "auto_apply_weekly_limit": 20,
            "auto_apply_daily_per_employer_limit": 2,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 0,
        },
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _session(user_id: int) -> ShadowRunSession:
    started = datetime.now(timezone.utc)
    return ShadowRunSession(
        user_id=user_id,
        candidate_revision=REVISION,
        target_evidence_type="shadow_run_4h",
        requested_duration_seconds=4 * 60 * 60,
        cycle_interval_seconds=15 * 60,
        status="scheduled",
        started_at=started,
        expected_end_at=started + timedelta(hours=4),
        settle_deadline_at=started + timedelta(hours=4, minutes=45),
        last_heartbeat_at=started,
        final_submit_allowed=False,
        stop_requested=False,
        configuration_snapshot={},
        baseline_snapshot={},
    )


def _install_safe_android(monkeypatch, *, followup_send: bool = False) -> None:
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    operations = _operations()
    monkeypatch.setattr(operations_policy, "get_operations_settings", lambda: operations)
    monkeypatch.setattr(shadow_qualification, "get_operations_settings", lambda: operations)
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            allow_real_application_submit=False,
            allow_real_followup_send=followup_send,
        ),
    )
    monkeypatch.setattr(
        runtime_acceptance,
        "canary_receipt_status",
        lambda user_id, **_kwargs: {
            "ok": True,
            "blockers": [],
            "receipt": {
                "type": "shadow_qualification_canary",
                "user_id": int(user_id),
                "revision": REVISION,
                "certification_eligible": False,
            },
        },
    )


def test_android_four_hour_insert_rechecks_live_policy_after_canary(db_session, monkeypatch):
    _install_safe_android(monkeypatch)
    user = _user(db_session, policy_version="stale-policy-version")
    db_session.add(_session(int(user.id)))

    with pytest.raises(ValueError, match="scheduler_policy_version_current"):
        db_session.flush()


def test_android_four_hour_insert_rejects_outreach_permission_drift(db_session, monkeypatch):
    _install_safe_android(monkeypatch, followup_send=True)
    user = _user(db_session)
    db_session.add(_session(int(user.id)))

    with pytest.raises(ValueError, match="outreach_not_disabled"):
        db_session.flush()


def test_android_four_hour_insert_accepts_fresh_canary_and_current_live_policy(db_session, monkeypatch):
    _install_safe_android(monkeypatch)
    user = _user(db_session)
    session = _session(int(user.id))
    db_session.add(session)
    db_session.flush()

    assert session.id is not None
    assert session.active_guard == f"user:{int(user.id)}"
    assert session.final_submit_allowed is False
