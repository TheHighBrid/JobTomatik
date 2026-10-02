from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from app.api import supervised_pilot_roster as api_module
from app.models.submission_approval import SubmissionApproval
from app.models.submission_integrity import SubmissionAttempt
from app.services import lever_pilot_control_request as control


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40
SECRET = "s" * 48


def _paths(tmp_path: Path):
    control_dir = tmp_path / "pilot-control"
    return (
        control_dir / "request.json",
        control_dir / "inflight.json",
        control_dir / "status.json",
        control_dir / "lease-owner.json",
        control_dir / "controller-heartbeat",
    )


def _patch_secret(monkeypatch):
    monkeypatch.setattr(control, "_settings_secret", lambda: SECRET)


def test_signed_request_is_claimed_once_and_completed(tmp_path, monkeypatch):
    _patch_secret(monkeypatch)
    request_path, inflight_path, status_path, owner_path, _heartbeat = _paths(tmp_path)
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(control, "_now", lambda: 1000)

    request = control._create_request(
        action="arm",
        user=user,
        runtime_revision=REVISION,
        application_id=247,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )

    serialized = request_path.read_text(encoding="utf-8")
    stored = json.loads(serialized)
    assert request["application_id"] == 247
    assert SECRET not in serialized
    assert len(stored["signature"]) == 64
    assert request_path.stat().st_mode & 0o777 == 0o600

    claimed = control.claim_control_request(
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )
    assert claimed is not None
    assert claimed["request_id"] == request["request_id"]
    assert request_path.exists() is False
    assert inflight_path.exists() is True

    # The same signed request cannot be claimed a second time while inflight.
    assert control.claim_control_request(
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    ) is None

    monkeypatch.setattr(control, "_now", lambda: 1010)
    result = control.complete_control_request(
        request_id=request["request_id"],
        outcome="success",
        exit_code=0,
        inflight_path=inflight_path,
        status_path=status_path,
        owner_path=owner_path,
    )
    assert result["outcome"] == "success"
    assert result["application_id"] == 247
    assert inflight_path.exists() is False
    assert control._record_signature_valid(result, SECRET) is True

    owner = json.loads(owner_path.read_text(encoding="utf-8"))
    assert owner["user_id"] == 7
    assert owner["application_id"] == 247
    assert owner["kind"] == "lever_supervised_lease_owner"
    assert control._record_signature_valid(owner, SECRET) is True


def test_request_publication_serializes_single_slot(tmp_path, monkeypatch):
    _patch_secret(monkeypatch)
    request_path, inflight_path, status_path, _owner_path, _heartbeat = _paths(tmp_path)
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(control, "_now", lambda: 1000)

    original_atomic_write = control._atomic_write_json
    first_write_entered = threading.Event()
    release_first_write = threading.Event()
    call_lock = threading.Lock()
    request_write_count = 0

    def delayed_atomic_write(path, value):
        nonlocal request_write_count
        if path == request_path:
            with call_lock:
                request_write_count += 1
                call_number = request_write_count
            if call_number == 1:
                first_write_entered.set()
                assert release_first_write.wait(timeout=2)
        return original_atomic_write(path, value)

    monkeypatch.setattr(control, "_atomic_write_json", delayed_atomic_write)

    def create(application_id):
        return control._create_request(
            action="arm",
            user=user,
            runtime_revision=REVISION,
            application_id=application_id,
            request_path=request_path,
            inflight_path=inflight_path,
            status_path=status_path,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(create, 247)
        assert first_write_entered.wait(timeout=1)
        second = executor.submit(create, 248)
        time.sleep(0.05)
        assert second.done() is False
        release_first_write.set()

        assert first.result(timeout=2)["application_id"] == 247
        with pytest.raises(
            control.LeverPilotControlError,
            match="REQUEST_ALREADY_PENDING",
        ):
            second.result(timeout=2)

    stored = json.loads(request_path.read_text(encoding="utf-8"))
    assert stored["application_id"] == 247
    assert request_write_count == 1


def test_controller_restart_marks_inflight_uncertain_without_replay(tmp_path, monkeypatch):
    _patch_secret(monkeypatch)
    request_path, inflight_path, status_path, _owner_path, _heartbeat = _paths(tmp_path)
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(control, "_now", lambda: 1000)
    request = control._create_request(
        action="arm",
        user=user,
        runtime_revision=REVISION,
        application_id=247,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )
    assert control.claim_control_request(
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )

    monkeypatch.setattr(control, "_now", lambda: 1020)
    recovered = control.recover_inflight_without_replay(
        inflight_path=inflight_path,
        status_path=status_path,
    )

    assert recovered is not None
    assert recovered["request_id"] == request["request_id"]
    assert recovered["outcome"] == "uncertain_no_replay"
    assert inflight_path.exists() is False
    assert request_path.exists() is False


def test_expired_unclaimed_request_is_never_executed(tmp_path, monkeypatch):
    _patch_secret(monkeypatch)
    request_path, inflight_path, status_path, _owner_path, _heartbeat = _paths(tmp_path)
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(control, "_now", lambda: 1000)
    control._create_request(
        action="arm",
        user=user,
        runtime_revision=REVISION,
        application_id=247,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )

    monkeypatch.setattr(control, "_now", lambda: 2000)
    claimed = control.claim_control_request(
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )

    assert claimed is None
    assert request_path.exists() is False
    assert inflight_path.exists() is False
    assert json.loads(status_path.read_text(encoding="utf-8"))["outcome"] == "expired"


def test_arm_service_requires_exact_ack_controller_and_inactive_lease(monkeypatch):
    user = SimpleNamespace(id=7)
    db = object()
    monkeypatch.setattr(control, "_runtime_revision_from_environment", lambda: REVISION)
    monkeypatch.setattr(control, "_owned_ready_lever_application", lambda *_args, **_kwargs: (object(), object()))
    monkeypatch.setattr(control, "_heartbeat_fresh", lambda: True)
    monkeypatch.setattr(control, "runtime_lease_status", lambda **_kwargs: {"active": False})
    monkeypatch.setattr(
        control,
        "_create_request",
        lambda **kwargs: {
            "request_id": "pilot-control-test",
            "action": kwargs["action"],
            "application_id": kwargs["application_id"],
            "runtime_revision": kwargs["runtime_revision"],
        },
    )

    with pytest.raises(control.LeverPilotControlError, match="ACKNOWLEDGMENT_REQUIRED"):
        control.request_runtime_arm(
            db,
            user,
            application_id=247,
            acknowledgment="ENABLE LEVER SUPERVISED WINDOW 246",
        )

    monkeypatch.setattr(control, "_heartbeat_fresh", lambda: False)
    with pytest.raises(control.LeverPilotControlError, match="CONTROLLER_UNAVAILABLE"):
        control.request_runtime_arm(
            db,
            user,
            application_id=247,
            acknowledgment="ENABLE LEVER SUPERVISED WINDOW 247",
        )

    monkeypatch.setattr(control, "_heartbeat_fresh", lambda: True)
    monkeypatch.setattr(control, "runtime_lease_status", lambda **_kwargs: {"active": True})
    with pytest.raises(control.LeverPilotControlError, match="ALREADY_ACTIVE"):
        control.request_runtime_arm(
            db,
            user,
            application_id=247,
            acknowledgment="ENABLE LEVER SUPERVISED WINDOW 247",
        )

    monkeypatch.setattr(control, "runtime_lease_status", lambda **_kwargs: {"active": False})
    result = control.request_runtime_arm(
        db,
        user,
        application_id=247,
        acknowledgment="ENABLE LEVER SUPERVISED WINDOW 247",
    )
    assert result["accepted"] is True
    assert result["request"]["application_id"] == 247
    assert result["submission_approval_issued"] is False
    assert result["submission_queued"] is False
    assert result["persisted_runtime_flags_changed"] is False


def test_disarm_requires_signed_current_lease_owner(tmp_path, monkeypatch):
    _patch_secret(monkeypatch)
    request_path, inflight_path, status_path, owner_path, _heartbeat = _paths(tmp_path)
    owner = SimpleNamespace(id=7)
    other_user = SimpleNamespace(id=8)
    monkeypatch.setattr(control, "_runtime_revision_from_environment", lambda: REVISION)
    monkeypatch.setattr(control, "_heartbeat_fresh", lambda: True)
    monkeypatch.setattr(control, "runtime_lease_status", lambda **_kwargs: {"active": True})
    monkeypatch.setattr(control, "_now", lambda: 1000)

    control._write_owner_record(
        {
            "request_id": "pilot-control-owner",
            "application_id": 247,
            "user_id": owner.id,
            "runtime_revision": REVISION,
        },
        owner_path=owner_path,
        secret_key=SECRET,
    )

    with pytest.raises(control.LeverPilotControlError, match="DISARM_OWNER_REQUIRED"):
        control.request_runtime_disarm(
            other_user,
            request_path=request_path,
            inflight_path=inflight_path,
            status_path=status_path,
            owner_path=owner_path,
        )

    result = control.request_runtime_disarm(
        owner,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
        owner_path=owner_path,
    )
    assert result["accepted"] is True
    assert result["request"]["action"] == "disarm"


def test_successful_disarm_clears_owner_but_failed_disarm_preserves_it(tmp_path, monkeypatch):
    _patch_secret(monkeypatch)
    request_path, inflight_path, status_path, owner_path, _heartbeat = _paths(tmp_path)
    user = SimpleNamespace(id=7)
    monkeypatch.setattr(control, "_now", lambda: 1000)

    control._write_owner_record(
        {
            "request_id": "pilot-control-arm-owner",
            "application_id": 247,
            "user_id": user.id,
            "runtime_revision": REVISION,
        },
        owner_path=owner_path,
        secret_key=SECRET,
    )

    failed = control._create_request(
        action="disarm",
        user=user,
        runtime_revision=REVISION,
        application_id=None,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )
    control.claim_control_request(
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )
    control.complete_control_request(
        request_id=failed["request_id"],
        outcome="failed",
        exit_code=1,
        inflight_path=inflight_path,
        status_path=status_path,
        owner_path=owner_path,
    )
    assert owner_path.exists() is True

    succeeded = control._create_request(
        action="disarm",
        user=user,
        runtime_revision=REVISION,
        application_id=None,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )
    control.claim_control_request(
        runtime_revision=REVISION,
        request_path=request_path,
        inflight_path=inflight_path,
        status_path=status_path,
    )
    control.complete_control_request(
        request_id=succeeded["request_id"],
        outcome="success",
        exit_code=0,
        inflight_path=inflight_path,
        status_path=status_path,
        owner_path=owner_path,
    )
    assert owner_path.exists() is False


def test_runtime_control_api_has_no_submission_authority(auth_client, db_session, monkeypatch):
    observed = []

    monkeypatch.setattr(
        api_module,
        "runtime_control_status",
        lambda user: {
            "available": True,
            "controller_available": True,
            "runtime_revision": REVISION,
            "lease_active": False,
            "lease_owned_by_current_user": False,
            "can_disarm": False,
            "transition_state": "idle",
            "submission_approval_issued": False,
            "submission_queued": False,
            "persisted_runtime_flags_changed": False,
        },
    )

    def arm(_db, user, *, application_id, acknowledgment):
        observed.append(("arm", user.id, application_id, acknowledgment))
        return {
            "accepted": True,
            "request": {"application_id": application_id, "action": "arm"},
            "submission_approval_issued": False,
            "submission_queued": False,
            "persisted_runtime_flags_changed": False,
        }

    def disarm(user):
        observed.append(("disarm", user.id))
        return {
            "accepted": True,
            "request": {"application_id": None, "action": "disarm"},
            "submission_approval_issued": False,
            "submission_queued": False,
            "persisted_runtime_flags_changed": False,
        }

    monkeypatch.setattr(api_module, "request_runtime_arm", arm)
    monkeypatch.setattr(api_module, "request_runtime_disarm", disarm)

    status = auth_client.get("/api/supervised-pilot/current-lever/runtime-control")
    assert status.status_code == 200, status.text
    assert status.json()["submission_approval_issued"] is False

    arm_response = auth_client.post(
        "/api/supervised-pilot/current-lever/247/runtime-control/arm",
        json={"acknowledgment": "ENABLE LEVER SUPERVISED WINDOW 247"},
    )
    assert arm_response.status_code == 202, arm_response.text
    assert arm_response.json()["submission_queued"] is False

    disarm_response = auth_client.post(
        "/api/supervised-pilot/current-lever/runtime-control/disarm"
    )
    assert disarm_response.status_code == 202, disarm_response.text
    assert disarm_response.json()["persisted_runtime_flags_changed"] is False

    assert observed[0][0:3] == ("arm", observed[0][1], 247)
    assert observed[0][3] == "ENABLE LEVER SUPERVISED WINDOW 247"
    assert observed[1][0] == "disarm"
    assert db_session.query(SubmissionApproval).count() == 0
    assert db_session.query(SubmissionAttempt).count() == 0


def test_native_controller_scripts_are_syntax_valid_and_fail_closed():
    scripts = {
        "daemon": BACKEND_ROOT / "scripts/jobtomatik_pilot_control_daemon.sh",
        "manager": BACKEND_ROOT / "scripts/jobtomatik_pilot_controller_manager.sh",
        "installer": BACKEND_ROOT / "scripts/install_android_native_browser_launcher.sh",
        "stack": BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh",
    }
    for path in scripts.values():
        subprocess.run(["bash", "-n", str(path)], check=True)

    daemon = scripts["daemon"].read_text(encoding="utf-8")
    manager = scripts["manager"].read_text(encoding="utf-8")
    installer = scripts["installer"].read_text(encoding="utf-8")
    stack = scripts["stack"].read_text(encoding="utf-8")

    assert daemon.index("recover-inflight") < daemon.index("while true")
    assert "NATIVE_TMPDIR=\"${TMPDIR:-${PREFIX:-/data/data/com.termux/files/usr}/tmp}\"" in daemon
    assert "NATIVE_CONTROL_DIR=" in daemon
    assert "GUEST_CONTROL_DIR=" in daemon
    assert 'HEARTBEAT_PATH="$NATIVE_CONTROL_DIR/controller-heartbeat"' in daemon
    assert '--control-dir %q' in daemon
    assert '"$PROOT_REPO/backend" "$action" "$GUEST_CONTROL_DIR"' in daemon
    assert '[[ -f "$NATIVE_CONTROL_DIR/request.json" ]]' in daemon
    assert "claim-request" in daemon
    assert "complete-request" in daemon
    assert "uncertain_no_replay" in (
        BACKEND_ROOT / "app/services/lever_pilot_control_request.py"
    ).read_text(encoding="utf-8")
    assert "jobtomatik-pilot-controller" in manager
    assert "STALE_PILOT_CONTROLLER_PID_REJECTED" in manager
    assert "PILOT_CONTROLLER_SOURCE" in installer
    assert "PILOT_CONTROLLER_MANAGER_SOURCE" in installer
    assert "ensure_pilot_controller" in stack
    assert "stop_pilot_controller" in stack
    assert stack.index("stop_pilot_controller") < stack.index("stop_stack_supervisor", stack.index('  stop)'))
