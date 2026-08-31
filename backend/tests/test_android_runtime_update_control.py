from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from app.api import controller as controller_api
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import (
    ACTIVE_SUBMISSION_ATTEMPT_STATUSES,
    SubmissionAttempt,
    SubmissionAttemptStatus,
)
from app.services import android_runtime_update_control as update_control
from app.services import lever_pilot_control_request as pilot_control


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION = "b" * 40
SECRET = "u" * 48


def _paths(tmp_path: Path):
    control_dir = tmp_path / "pilot-control"
    return (
        control_dir / "request.json",
        control_dir / "inflight.json",
        control_dir / "status.json",
        control_dir / "controller-heartbeat",
        control_dir / "lease-owner.json",
    )


def _patch_secret(monkeypatch):
    monkeypatch.setattr(update_control, "_settings_secret", lambda: SECRET)
    monkeypatch.setattr(pilot_control, "_settings_secret", lambda: SECRET)


def _fake_db_for_user(user):
    class Query:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return user

    class DB:
        def query(self, *_args, **_kwargs):
            return Query()

    return DB()


def test_runtime_update_request_is_signed_one_shot_and_submission_free(
    tmp_path,
    monkeypatch,
):
    _patch_secret(monkeypatch)
    request_path, inflight_path, status_path, heartbeat_path, _owner_path = _paths(tmp_path)
    user = SimpleNamespace(id=7)
    db = object()

    monkeypatch.setattr(
        update_control,
        "_runtime_revision_from_environment",
        lambda: REVISION,
    )
    monkeypatch.setattr(update_control, "_heartbeat_fresh", lambda _path: True)
    monkeypatch.setattr(
        update_control,
        "runtime_lease_status",
        lambda **_kwargs: {"active": False},
    )
    monkeypatch.setattr(
        update_control,
        "_owner_has_executing_submission_attempt",
        lambda *_args: False,
    )
    monkeypatch.setattr(update_control, "_now", lambda: 1000)

    result = update_control.request_runtime_update(
        db,
        user,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
        heartbeat_path=heartbeat_path,
    )

    assert result["accepted"] is True
    assert result["runtime_update_requested"] is True
    assert result["submission_approval_issued"] is False
    assert result["submission_queued"] is False
    assert result["persisted_runtime_flags_changed"] is False
    assert result["request"]["action"] == "update"
    assert result["request"]["application_id"] is None

    stored = json.loads(request_path.read_text(encoding="utf-8"))
    assert stored["action"] == "update"
    assert stored["runtime_revision"] == REVISION
    assert stored["user_id"] == user.id
    assert pilot_control._record_signature_valid(stored, SECRET) is True
    assert request_path.stat().st_mode & 0o777 == 0o600


def test_runtime_update_is_blocked_by_controller_lease_or_executing_submission_state(
    tmp_path,
    monkeypatch,
):
    _patch_secret(monkeypatch)
    request_path, inflight_path, status_path, heartbeat_path, _owner_path = _paths(tmp_path)
    user = SimpleNamespace(id=7)
    db = object()

    monkeypatch.setattr(
        update_control,
        "_runtime_revision_from_environment",
        lambda: REVISION,
    )
    monkeypatch.setattr(update_control, "_heartbeat_fresh", lambda _path: False)
    monkeypatch.setattr(
        update_control,
        "runtime_lease_status",
        lambda **_kwargs: {"active": False},
    )
    monkeypatch.setattr(
        update_control,
        "_owner_has_executing_submission_attempt",
        lambda *_args: False,
    )

    with pytest.raises(
        pilot_control.LeverPilotControlError,
        match="NATIVE_CONTROLLER_UNAVAILABLE",
    ):
        update_control.request_runtime_update(
            db,
            user,
            request_path=request_path,
            inflight_path=inflight_path,
            status_path=status_path,
            heartbeat_path=heartbeat_path,
        )

    monkeypatch.setattr(update_control, "_heartbeat_fresh", lambda _path: True)
    monkeypatch.setattr(
        update_control,
        "runtime_lease_status",
        lambda **_kwargs: {"active": True},
    )
    with pytest.raises(
        pilot_control.LeverPilotControlError,
        match="SUPERVISED_WINDOW_ACTIVE",
    ):
        update_control.request_runtime_update(
            db,
            user,
            request_path=request_path,
            inflight_path=inflight_path,
            status_path=status_path,
            heartbeat_path=heartbeat_path,
        )

    monkeypatch.setattr(
        update_control,
        "runtime_lease_status",
        lambda **_kwargs: {"active": False},
    )
    monkeypatch.setattr(
        update_control,
        "_owner_has_executing_submission_attempt",
        lambda *_args: True,
    )
    with pytest.raises(
        pilot_control.LeverPilotControlError,
        match="EXECUTING_SUBMISSION_ATTEMPT",
    ):
        update_control.request_runtime_update(
            db,
            user,
            request_path=request_path,
            inflight_path=inflight_path,
            status_path=status_path,
            heartbeat_path=heartbeat_path,
        )

    assert request_path.exists() is False
    assert inflight_path.exists() is False


def test_uncertain_quarantine_does_not_permanently_lock_runtime_maintenance():
    assert update_control.EXECUTING_SUBMISSION_ATTEMPT_STATUSES == (
        SubmissionAttemptStatus.queued.value,
        SubmissionAttemptStatus.in_progress.value,
    )
    assert (
        SubmissionAttemptStatus.uncertain.value
        not in update_control.EXECUTING_SUBMISSION_ATTEMPT_STATUSES
    )
    # Quarantine semantics remain stricter than runtime-maintenance semantics.
    # An uncertain application still cannot mutate materials or retry automatically.
    assert SubmissionAttemptStatus.uncertain.value in ACTIVE_SUBMISSION_ATTEMPT_STATUSES


def test_native_claim_rechecks_update_safety_and_never_replays(
    tmp_path,
    monkeypatch,
):
    _patch_secret(monkeypatch)
    request_path, inflight_path, status_path, heartbeat_path, owner_path = _paths(tmp_path)
    user = SimpleNamespace(id=7)
    fake_db = _fake_db_for_user(user)

    monkeypatch.setattr(update_control, "_heartbeat_fresh", lambda _path: True)
    monkeypatch.setattr(
        update_control,
        "runtime_lease_status",
        lambda **_kwargs: {"active": False},
    )
    monkeypatch.setattr(
        update_control,
        "_owner_has_executing_submission_attempt",
        lambda *_args: False,
    )
    monkeypatch.setattr(update_control, "_now", lambda: 1000)

    request = update_control._create_update_request(
        fake_db,
        user,
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )
    claimed = update_control.claim_native_control_request(
        fake_db,
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )

    assert claimed is not None
    assert claimed["request_id"] == request["request_id"]
    assert claimed["action"] == "update"
    assert request_path.exists() is False
    assert inflight_path.exists() is True
    assert update_control.claim_native_control_request(
        fake_db,
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    ) is None

    pilot_control.complete_control_request(
        request_id=request["request_id"],
        outcome="success",
        exit_code=0,
        inflight_path=inflight_path,
        status_path=status_path,
        owner_path=owner_path,
    )
    assert inflight_path.exists() is False
    assert owner_path.exists() is False
    assert json.loads(status_path.read_text(encoding="utf-8"))["outcome"] == "success"


def test_native_claim_rejects_update_if_state_changes_after_publication(
    tmp_path,
    monkeypatch,
):
    _patch_secret(monkeypatch)
    request_path, inflight_path, status_path, _heartbeat_path, _owner_path = _paths(tmp_path)
    user = SimpleNamespace(id=7)
    fake_db = _fake_db_for_user(user)

    monkeypatch.setattr(
        update_control,
        "runtime_lease_status",
        lambda **_kwargs: {"active": False},
    )
    monkeypatch.setattr(
        update_control,
        "_owner_has_executing_submission_attempt",
        lambda *_args: False,
    )
    monkeypatch.setattr(update_control, "_now", lambda: 1000)
    update_control._create_update_request(
        fake_db,
        user,
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )

    monkeypatch.setattr(
        update_control,
        "runtime_lease_status",
        lambda **_kwargs: {"active": True},
    )
    claimed = update_control.claim_native_control_request(
        fake_db,
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )

    assert claimed is None
    assert request_path.exists() is False
    assert inflight_path.exists() is False
    assert json.loads(status_path.read_text(encoding="utf-8"))["outcome"] == "failed"


def test_android_runtime_update_api_has_no_submission_authority(
    auth_client,
    db_session,
    monkeypatch,
):
    observed = []

    def request_update(db, user):
        observed.append((db, user.id))
        return {
            "accepted": True,
            "request": {"action": "update", "application_id": None},
            "runtime_update_requested": True,
            "submission_approval_issued": False,
            "submission_queued": False,
            "persisted_runtime_flags_changed": False,
        }

    monkeypatch.setattr(controller_api, "request_runtime_update", request_update)
    response = auth_client.post("/api/controller/android-runtime/update")

    assert response.status_code == 202, response.text
    assert response.json()["runtime_update_requested"] is True
    assert response.json()["submission_approval_issued"] is False
    assert response.json()["submission_queued"] is False
    assert observed and observed[0][1] > 0
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0


def test_native_update_mapping_is_fixed_and_shell_free():
    daemon = BACKEND_ROOT / "scripts/jobtomatik_pilot_control_daemon.sh"
    bridge = BACKEND_ROOT / "scripts/lever_supervised_pilot_control_bridge.py"
    stack = BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh"

    subprocess.run(["bash", "-n", str(daemon)], check=True)
    daemon_text = daemon.read_text(encoding="utf-8")
    bridge_text = bridge.read_text(encoding="utf-8")
    stack_text = stack.read_text(encoding="utf-8")

    assert '"$action" != "update"' in daemon_text
    assert 'if [[ "$action" == "update" ]]; then' in daemon_text
    assert '"$STACK_COMMAND" update' in daemon_text
    assert "eval " not in daemon_text
    assert "claim_native_control_request" in bridge_text
    assert '  update)' in stack_text
    assert 'exec "${JOBTOMATIK_STACK_COMMAND:-$0}" restart' in stack_text
