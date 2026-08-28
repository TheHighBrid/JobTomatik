from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.api.autonomy_control import router as autonomy_router
from app.api.live_pilot import LivePilotAuthorizeRequest
from app.models.application import Application, ApplicationStatus
from app.models.job import Job, JobSource, JobStatus
from app.models.user import User
from app.services import day39_live_runtime
from app.services.day39_live_authorization import create_live_pilot_authorization
from app.services.day39_live_runtime import reserve_canonical_day39_live_attempt
from app.services.day39_live_window import expected_live_window_acknowledgment
from app.services.operations_policy import AutomationDecision
from app.tasks import unattended


REVISION = "c" * 40
NOW = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)


def _manifest(revision: str = REVISION):
    return {
        "adapters": [
            {
                "name": "lever",
                "version": "1.1.0",
                "maturity": "certified_autonomous",
                "autonomous_submission_allowed": True,
                "release_gate_status": {
                    "certified_autonomous": {
                        "passed": True,
                        "certification_manifest": {
                            "passed": True,
                            "release_commit": revision,
                        },
                    }
                },
            }
        ]
    }


def _runtime(revision: str = REVISION):
    return {
        "revision": revision,
        "known": True,
        "deployment_attested": True,
    }


def _seed(db_session, *, email: str = "day39-live-enforcement@example.test"):
    user = User(
        email=email,
        hashed_password="test-hash",
        automation_settings={},
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    job = Job(
        external_id=f"{email}-job",
        title="Day 39 Live Pilot",
        company="Live Pilot Example",
        location="ottawa, ontario",
        salary_min=90000,
        seniority="mid",
        source=JobSource.lever,
        status=JobStatus.approved,
        relevance_score=0.99,
        url="https://jobs.lever.co/live-pilot/example",
        raw_data={"language": "english", "requires_sponsorship": False},
    )
    db_session.add(job)
    db_session.flush()
    app = Application(
        user_id=user.id,
        job_id=job.id,
        status=ApplicationStatus.pending,
    )
    db_session.add(app)
    db_session.commit()
    return user, job, app


def _authorization(db_session, *, user_id: int):
    owner = {
        "approved": True,
        "approval_reference": "day39-first-wave-owner",
        "approved_for_commit": REVISION,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "max_submission_attempts": 2,
        "starts_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=6)).isoformat(),
        "acknowledgment": expected_live_window_acknowledgment(
            revision=REVISION,
            attempt_cap=2,
        ),
    }
    record, report = create_live_pilot_authorization(
        db_session,
        approved_by_user_id=user_id,
        promotion={
            "passed": True,
            "promotion_authorized": True,
            "live_window_authorized": False,
            "real_submission_authorized": False,
            "release_candidate_revision": REVISION,
            "target_adapter": "lever",
            "target_adapter_version": "1.1.0",
            "target_maturity": "certified_autonomous",
        },
        adapter_state={
            "name": "lever",
            "version": "1.1.0",
            "maturity": "certified_autonomous",
            "autonomous_submission_allowed": True,
        },
        runtime_safety={
            "current_revision": REVISION,
            "allow_real_application_submit": False,
            "allow_real_followup_send": False,
            "global_kill_switch": False,
            "live_window_authorized": False,
        },
        policy_state={
            "ready": True,
            "policy_profile": "production",
            "circuit_breaker_clear": True,
            "quiet_hours_active": False,
            "remaining_daily": 5,
            "remaining_weekly": 20,
        },
        owner_request=owner,
        now=NOW,
    )
    assert record is not None
    assert report["authorization_persisted"] is True
    db_session.commit()
    return record


def _enable_live_runtime(monkeypatch):
    monkeypatch.setattr(
        day39_live_runtime,
        "get_settings",
        lambda: SimpleNamespace(
            allow_real_application_submit=True,
            allow_real_followup_send=False,
        ),
    )
    monkeypatch.setattr(
        day39_live_runtime,
        "get_operations_settings",
        lambda: SimpleNamespace(global_kill_switch=False),
    )


def test_owner_api_schema_rejects_forged_authority_fields():
    with pytest.raises(ValidationError):
        LivePilotAuthorizeRequest.model_validate(
            {
                "approval_reference": "owner-ref",
                "max_submission_attempts": 2,
                "window_minutes": 60,
                "acknowledgment": "not-the-point-of-this-test",
                "promotion_passed": True,
                "maturity": "certified_autonomous",
                "release_candidate_revision": "f" * 40,
            }
        )


def test_live_pilot_routes_are_nested_under_authenticated_autonomy_control():
    paths = {route.path for route in autonomy_router.routes}
    assert "/autonomy-control/live-pilot/preflight" in paths
    assert "/autonomy-control/live-pilot/authorize" in paths
    assert "/autonomy-control/live-pilot/status" in paths
    assert "/autonomy-control/live-pilot/{authorization_id}/revoke" in paths


def test_global_submit_flag_alone_is_never_live_authority(db_session, monkeypatch):
    user, _job, app = _seed(db_session, email="flag-alone@example.test")
    _enable_live_runtime(monkeypatch)

    result = reserve_canonical_day39_live_attempt(
        db_session,
        user_id=user.id,
        application_id=app.id,
        platform="lever",
        now=NOW + timedelta(minutes=1),
        manifest=_manifest(),
        runtime_manifest=_runtime(),
    )

    assert result["allowed"] is False
    assert result["reason"] == "active_live_pilot_authorization_missing"


def test_exact_authorization_and_runtime_reserve_nonreclaiming_slot(db_session, monkeypatch):
    user, _job, app = _seed(db_session, email="exact-live@example.test")
    authorization = _authorization(db_session, user_id=user.id)
    _enable_live_runtime(monkeypatch)

    result = reserve_canonical_day39_live_attempt(
        db_session,
        user_id=user.id,
        application_id=app.id,
        platform="lever",
        now=NOW + timedelta(minutes=1),
        manifest=_manifest(),
        runtime_manifest=_runtime(),
    )

    assert result["allowed"] is True
    assert result["reason"] == "live_pilot_attempt_reserved"
    assert result["attempts_reserved"] == 1
    db_session.refresh(authorization)
    assert authorization.reserved_submission_attempts == 1


def test_wrong_runtime_revision_blocks_before_attempt_reservation(db_session, monkeypatch):
    user, _job, app = _seed(db_session, email="wrong-revision@example.test")
    authorization = _authorization(db_session, user_id=user.id)
    _enable_live_runtime(monkeypatch)

    result = reserve_canonical_day39_live_attempt(
        db_session,
        user_id=user.id,
        application_id=app.id,
        platform="lever",
        now=NOW + timedelta(minutes=1),
        manifest=_manifest(),
        runtime_manifest=_runtime("d" * 40),
    )

    assert result == {"allowed": False, "reason": "live_pilot_runtime_revision_unattested"}
    db_session.refresh(authorization)
    assert authorization.reserved_submission_attempts == 0


def _allow_policy(monkeypatch):
    monkeypatch.setattr(
        unattended,
        "evaluate_unattended_job_policy",
        lambda db, user, job: AutomationDecision(
            True,
            "autopilot_allowed",
            "allowed",
            {"platform": "lever"},
        ),
    )


def test_worker_never_calls_submission_when_live_authority_blocks(db_session, monkeypatch):
    _user, _job, app = _seed(db_session, email="worker-block@example.test")
    monkeypatch.setattr(unattended, "SessionLocal", lambda: db_session)
    _allow_policy(monkeypatch)
    live_gate = MagicMock(
        return_value={
            "allowed": False,
            "success": False,
            "error": "active_live_pilot_authorization_missing",
        }
    )
    monkeypatch.setattr(unattended, "enforce_day39_live_worker_gate", live_gate)
    downstream = MagicMock(return_value={"success": True})
    monkeypatch.setattr("app.tasks.applications.submit_application_task.run", downstream)

    result = unattended.submit_unattended_application_task.run(app.id, dry_run=False)

    assert result["success"] is False
    assert result["error"] == "active_live_pilot_authorization_missing"
    live_gate.assert_called_once()
    downstream.assert_not_called()


def test_worker_dry_run_never_consumes_live_authorization(db_session, monkeypatch):
    _user, _job, app = _seed(db_session, email="worker-dry-run@example.test")
    monkeypatch.setattr(unattended, "SessionLocal", lambda: db_session)
    _allow_policy(monkeypatch)
    live_gate = MagicMock(side_effect=AssertionError("dry-run must not reach live-pilot gate"))
    monkeypatch.setattr(unattended, "enforce_day39_live_worker_gate", live_gate)
    downstream = MagicMock(return_value={"success": True, "dry_run": True})
    monkeypatch.setattr("app.tasks.applications.submit_application_task.run", downstream)

    result = unattended.submit_unattended_application_task.run(app.id, dry_run=True)

    assert result["success"] is True
    live_gate.assert_not_called()
    downstream.assert_called_once_with(app.id, dry_run=True)


def test_worker_calls_submission_only_after_live_gate_allows(db_session, monkeypatch):
    _user, _job, app = _seed(db_session, email="worker-pass@example.test")
    monkeypatch.setattr(unattended, "SessionLocal", lambda: db_session)
    _allow_policy(monkeypatch)
    live_gate = MagicMock(
        return_value={
            "allowed": True,
            "success": True,
            "reservation": {"reservation_id": 99},
        }
    )
    monkeypatch.setattr(unattended, "enforce_day39_live_worker_gate", live_gate)
    downstream = MagicMock(return_value={"success": True, "dry_run": False})
    monkeypatch.setattr("app.tasks.applications.submit_application_task.run", downstream)

    result = unattended.submit_unattended_application_task.run(app.id, dry_run=False)

    assert result["success"] is True
    live_gate.assert_called_once()
    downstream.assert_called_once_with(app.id, dry_run=False)
