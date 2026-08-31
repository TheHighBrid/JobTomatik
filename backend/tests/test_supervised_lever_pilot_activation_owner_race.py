from __future__ import annotations

from pathlib import Path

import pytest

from app.services import supervised_runtime_mode


REVISION = "a" * 40
LAUNCH_TOKEN = "restart-capability-token-" + ("x" * 40)
OWNER_PID = 4242
API_PID = 5101
WORKER_PID = 5102


def test_activation_rechecks_owner_after_managed_process_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker_path = tmp_path / "lease.json"
    receipt = tmp_path / "android-runtime-acceptance.json"
    receipt.write_text('{"status":"pass"}\n', encoding="utf-8")
    owner = {
        "start_ticks": 123456,
        "cmdline": (
            "/data/data/com.termux/files/usr/bin/bash "
            "/data/data/com.termux/files/usr/bin/jobtomatik-pilot arm"
        ),
    }

    monkeypatch.setattr(
        supervised_runtime_mode,
        "_process_start_ticks",
        lambda pid: owner["start_ticks"] if pid == OWNER_PID else None,
    )
    monkeypatch.setattr(
        supervised_runtime_mode,
        "_process_cmdline",
        lambda pid: owner["cmdline"] if pid == OWNER_PID else "",
    )
    monkeypatch.setattr(supervised_runtime_mode, "RUNTIME_ACCEPTANCE_PATH", receipt)

    supervised_runtime_mode.create_owner_bound_marker(
        OWNER_PID,
        launch_token=LAUNCH_TOKEN,
        runtime_revision=REVISION,
        path=marker_path,
    )

    monkeypatch.setattr(
        supervised_runtime_mode,
        "_pid_file_value",
        lambda path: API_PID if path.name == "api.pid" else WORKER_PID,
    )
    managed_calls = {"count": 0}

    def managed_identity(role: str, pid: int, *, runtime_revision: str):
        managed_calls["count"] += 1
        expected_pid = API_PID if role == "api" else WORKER_PID
        identity = {
            "pid": expected_pid,
            "start_ticks": 81001 if role == "api" else 81002,
            "cmdline_sha256": ("1" if role == "api" else "2") * 64,
        }
        if managed_calls["count"] == len(supervised_runtime_mode.MANAGED_RUNTIME_ROLES):
            # Model SIGKILL of the native owner after both managed processes were
            # attested but before the active marker can be committed.
            owner["start_ticks"] = None
            owner["cmdline"] = ""
        assert pid == expected_pid
        assert runtime_revision == REVISION
        return identity

    monkeypatch.setattr(
        supervised_runtime_mode,
        "_managed_process_identity",
        managed_identity,
    )

    with pytest.raises(RuntimeError, match="OWNER_EXPIRED_BEFORE_ACTIVATION"):
        supervised_runtime_mode.activate_runtime_lease(
            launch_token=LAUNCH_TOKEN,
            runtime_revision=REVISION,
            path=marker_path,
        )

    marker = supervised_runtime_mode.load_marker(marker_path)
    assert marker is not None
    assert marker["state"] == supervised_runtime_mode.MARKER_STATE_PENDING
    assert supervised_runtime_mode.runtime_lease_status(marker_path)["active"] is False
    assert receipt.exists() is True
