from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import shadow_runs as shadow_api
from app.models.user import User


REVISION = "b" * 40


def _user(db_session, email: str) -> User:
    user = User(
        email=email,
        hashed_password="qualification-account-test-hash",
        automation_settings={},
        job_preferences={},
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _valid_admission(user_id: int) -> dict:
    return {
        "ok": True,
        "blockers": [],
        "receipt": {
            "status": "pass",
            "type": "shadow_qualification_canary",
            "user_id": int(user_id),
            "revision": REVISION,
            "runtime_fingerprint_sha256": "f" * 64,
            "application": {"application_id": 91},
            "certification_eligible": False,
        },
    }


def test_android_account_qualification_is_required_only_for_managed_four_hour(monkeypatch):
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_MODE", raising=False)
    assert shadow_api._android_account_qualification_required("shadow_run_4h") is False

    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    assert shadow_api._android_account_qualification_required("shadow_run_4h") is True
    assert shadow_api._android_account_qualification_required("shadow_run_8h") is False
    assert shadow_api._android_account_qualification_required("shadow_run_24h") is False


def test_three_active_users_never_trigger_database_user_guessing(db_session, monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    first = _user(db_session, "qualification-first@example.test")
    selected = _user(db_session, "qualification-selected@example.test")
    third = _user(db_session, "qualification-third@example.test")
    db_session.commit()

    status_calls: list[int] = []
    canary_calls: list[int] = []
    acceptance_refreshes: list[bool] = []

    def fake_status(user_id: int, **_kwargs):
        status_calls.append(int(user_id))
        if len(status_calls) == 1:
            # Simulate an unrelated account receipt plus stale runtime proof. Neither
            # condition may permit selecting another account from database contents.
            return {
                "ok": False,
                "blockers": ["user_matches", "runtime_acceptance_ready"],
                "receipt": {
                    "status": "pass",
                    "user_id": int(first.id),
                    "revision": REVISION,
                },
            }
        if len(status_calls) == 2:
            # Runtime refresh fixed only the physical proof. This account still has no
            # valid receipt, so the canary must run for the authenticated account.
            return {
                "ok": False,
                "blockers": ["user_matches"],
                "receipt": {
                    "status": "pass",
                    "user_id": int(first.id),
                    "revision": REVISION,
                },
            }
        return _valid_admission(int(selected.id))

    monkeypatch.setattr(shadow_api, "canary_receipt_status", fake_status)
    monkeypatch.setattr(
        shadow_api,
        "_refresh_android_runtime_acceptance",
        lambda: acceptance_refreshes.append(True) or {"status": "pass"},
    )
    monkeypatch.setattr(
        shadow_api,
        "_run_account_qualification",
        lambda user_id: canary_calls.append(int(user_id)) or {"status": "pass"},
    )

    result = shadow_api._ensure_android_account_qualification(
        user_id=int(selected.id),
        target_evidence_type="shadow_run_4h",
    )

    assert status_calls == [int(selected.id), int(selected.id), int(selected.id)]
    assert acceptance_refreshes == [True]
    assert canary_calls == [int(selected.id)]
    assert result["user_id"] == int(selected.id)
    assert result["performed"] is True
    assert int(first.id) not in canary_calls
    assert int(third.id) not in canary_calls


def test_exact_account_receipt_is_reused_without_another_real_canary(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.setattr(
        shadow_api,
        "canary_receipt_status",
        lambda user_id, **_kwargs: _valid_admission(int(user_id)),
    )

    canary_calls = []
    acceptance_refreshes = []
    monkeypatch.setattr(
        shadow_api,
        "_run_account_qualification",
        lambda user_id: canary_calls.append(int(user_id)),
    )
    monkeypatch.setattr(
        shadow_api,
        "_refresh_android_runtime_acceptance",
        lambda: acceptance_refreshes.append(True),
    )

    result = shadow_api._ensure_android_account_qualification(
        user_id=42,
        target_evidence_type="shadow_run_4h",
    )

    assert canary_calls == []
    assert acceptance_refreshes == []
    assert result["user_id"] == 42
    assert result["reused"] is True
    assert result["performed"] is False


def test_stale_runtime_receipt_is_refreshed_without_operator_action(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    status_calls: list[int] = []
    acceptance_refreshes: list[bool] = []
    canary_calls: list[int] = []

    def fake_status(user_id: int, **_kwargs):
        status_calls.append(int(user_id))
        if len(status_calls) == 1:
            return {
                "ok": False,
                "blockers": ["runtime_acceptance_ready"],
                "receipt": _valid_admission(int(user_id))["receipt"],
            }
        return _valid_admission(int(user_id))

    monkeypatch.setattr(shadow_api, "canary_receipt_status", fake_status)
    monkeypatch.setattr(
        shadow_api,
        "_refresh_android_runtime_acceptance",
        lambda: acceptance_refreshes.append(True) or {"status": "pass"},
    )
    monkeypatch.setattr(
        shadow_api,
        "_run_account_qualification",
        lambda user_id: canary_calls.append(int(user_id)),
    )

    result = shadow_api._ensure_android_account_qualification(
        user_id=77,
        target_evidence_type="shadow_run_4h",
    )

    assert status_calls == [77, 77]
    assert acceptance_refreshes == [True]
    assert canary_calls == []
    assert result["reused"] is True
    assert result["performed"] is False


def test_runtime_acceptance_failure_is_bounded_and_does_not_run_canary(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.setattr(
        shadow_api,
        "canary_receipt_status",
        lambda _user_id, **_kwargs: {
            "ok": False,
            "blockers": ["runtime_acceptance_ready"],
            "receipt": {},
        },
    )
    monkeypatch.setattr(
        shadow_api,
        "_refresh_android_runtime_acceptance",
        lambda: (_ for _ in ()).throw(RuntimeError("sensitive runtime detail")),
    )
    canary_calls = []
    monkeypatch.setattr(
        shadow_api,
        "_run_account_qualification",
        lambda user_id: canary_calls.append(int(user_id)),
    )

    with pytest.raises(HTTPException) as exc_info:
        shadow_api._ensure_android_account_qualification(
            user_id=7,
            target_evidence_type="shadow_run_4h",
        )

    assert canary_calls == []
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["reason"] == "android_runtime_acceptance_failed"
    assert "sensitive" not in str(detail)


def test_qualification_failure_never_exposes_raw_runtime_exception(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.setattr(
        shadow_api,
        "canary_receipt_status",
        lambda _user_id, **_kwargs: {
            "ok": False,
            "blockers": ["receipt_present"],
            "receipt": {},
        },
    )
    monkeypatch.setattr(
        shadow_api,
        "_refresh_android_runtime_acceptance",
        lambda: {"status": "pass"},
    )
    monkeypatch.setattr(
        shadow_api,
        "_run_account_qualification",
        lambda _user_id: (_ for _ in ()).throw(
            RuntimeError("redis://super-secret-password@127.0.0.1:6379/1")
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        shadow_api._ensure_android_account_qualification(
            user_id=7,
            target_evidence_type="shadow_run_4h",
        )

    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["reason"] == "account_qualification_failed"
    assert "redis://" not in str(detail)
    assert "secret" not in str(detail)


def test_start_route_passes_authenticated_account_to_qualification(
    auth_client,
    db_session,
    monkeypatch,
):
    authenticated = db_session.query(User).filter(User.email == "test@example.com").one()
    other_one = _user(db_session, "route-other-one@example.test")
    other_two = _user(db_session, "route-other-two@example.test")
    db_session.commit()

    expected_ack = f"START FULL STACK SHADOW shadow_run_4h {REVISION[:12]}"
    monkeypatch.setattr(
        shadow_api,
        "_runtime_identity_gate",
        lambda: {
            "required": True,
            "ok": True,
            "identity": {
                "deployment_attested": True,
                "revision": REVISION,
                "role": "api",
            },
        },
    )
    monkeypatch.setattr(
        shadow_api,
        "full_stack_shadow_preflight",
        lambda _db, _user, target_evidence_type="shadow_run_4h": {
            "ok": True,
            "blockers": [],
            "candidate_revision": REVISION,
            "target_evidence_type": target_evidence_type,
            "expected_start_acknowledgment": expected_ack,
        },
    )

    qualified_user_ids: list[int] = []

    def fake_qualification(*, user_id: int, target_evidence_type: str):
        assert target_evidence_type == "shadow_run_4h"
        qualified_user_ids.append(int(user_id))
        return {
            "required": True,
            "status": "pass",
            "performed": True,
            "reused": False,
            "user_id": int(user_id),
            "revision": REVISION,
            "certification_eligible": False,
        }

    monkeypatch.setattr(
        shadow_api,
        "_android_account_qualification_required",
        lambda target: target == "shadow_run_4h",
    )
    monkeypatch.setattr(
        shadow_api,
        "_ensure_android_account_qualification",
        fake_qualification,
    )
    monkeypatch.setattr(
        shadow_api,
        "create_shadow_session",
        lambda _db, *, user_id, target_evidence_type, acknowledgment, cycle_interval_seconds: SimpleNamespace(
            id=501,
            user_id=int(user_id),
            status="scheduled",
            candidate_revision=REVISION,
            target_evidence_type=target_evidence_type,
            requested_duration_seconds=4 * 60 * 60,
        ),
    )
    monkeypatch.setattr(db_session.__class__, "refresh", lambda self, _session: None)
    monkeypatch.setattr(
        shadow_api.run_shadow_session_cycle,
        "delay",
        lambda session_id: SimpleNamespace(id=f"task-{session_id}"),
    )
    monkeypatch.setattr(
        shadow_api,
        "_public_shadow_status",
        lambda _db, session: {"expected_end_at": "2026-08-13T06:00:00+00:00"},
    )

    response = auth_client.post(
        "/api/shadow-runs",
        json={
            "target_evidence_type": "shadow_run_4h",
            "cycle_interval_seconds": 60,
            "acknowledgment": expected_ack,
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert qualified_user_ids == [int(authenticated.id)]
    assert payload["qualification"]["user_id"] == int(authenticated.id)
    assert int(other_one.id) not in qualified_user_ids
    assert int(other_two.id) not in qualified_user_ids
