from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.config as config_module
from app.config import Settings
from app.services import supervised_runtime_mode
from app.services.supervised_runtime import supervised_target_scope
from app.services import supervised_target_identity
from scripts import lever_supervised_pilot_runtime as pilot_runtime


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40
LAUNCH_TOKEN = "restart-capability-token-" + ("x" * 40)
OWNER_PID = 4242
API_PID = 5101
WORKER_PID = 5102


def _write_env(path: Path, **overrides: str) -> None:
    values = {
        "SECRET_KEY": "s" * 48,
        "ALLOW_REAL_APPLICATION_SUBMIT": "false",
        "ALLOW_REAL_FOLLOWUP_SEND": "false",
        "GREENHOUSE_SUPERVISED_PILOT_ENABLED": "false",
        "LEVER_SUPERVISED_PILOT_ENABLED": "false",
        "AUTOPILOT_ENABLED": "false",
        "REDIS_URL": "redis://localhost:6379/1",
        "CUSTOM_OPERATOR_SETTING": "preserve-me",
    }
    values.update(overrides)
    path.write_text(
        "# operator configuration\n"
        + "\n".join(f"{key}={value}" for key, value in values.items())
        + "\n",
        encoding="utf-8",
    )


def _safe_settings() -> Settings:
    return Settings(
        _env_file=None,
        secret_key="s" * 48,
        allow_real_application_submit=False,
        allow_real_followup_send=False,
        greenhouse_supervised_pilot_enabled=False,
        lever_supervised_pilot_enabled=False,
    )


def _patch_pending_owner(monkeypatch, *, owner_ticks: int = 123456) -> dict:
    observed = {
        "owner_ticks": owner_ticks,
        "owner_cmdline": (
            "/data/data/com.termux/files/usr/bin/bash "
            "/data/data/com.termux/files/usr/bin/jobtomatik-pilot arm"
        ),
    }

    def process_ticks(pid: int):
        if pid == OWNER_PID:
            return observed["owner_ticks"]
        return None

    def process_cmdline(pid: int):
        if pid == OWNER_PID:
            return observed["owner_cmdline"]
        return ""

    monkeypatch.setattr(supervised_runtime_mode, "_process_start_ticks", process_ticks)
    monkeypatch.setattr(supervised_runtime_mode, "_process_cmdline", process_cmdline)
    return observed


def _patch_managed_processes(monkeypatch, *, revision: str = REVISION) -> dict:
    observed = {
        "api": {
            "pid": API_PID,
            "start_ticks": 81001,
            "cmdline_sha256": "1" * 64,
        },
        "worker": {
            "pid": WORKER_PID,
            "start_ticks": 81002,
            "cmdline_sha256": "2" * 64,
        },
    }

    def pid_file_value(path: Path):
        if path.name == "api.pid":
            return API_PID
        if path.name == "celery.pid":
            return WORKER_PID
        return None

    def identity(role: str, pid: int, *, runtime_revision: str):
        expected = observed.get(role)
        if runtime_revision != revision or not expected or pid != expected["pid"]:
            return None
        return dict(expected)

    monkeypatch.setattr(supervised_runtime_mode, "_pid_file_value", pid_file_value)
    monkeypatch.setattr(supervised_runtime_mode, "_managed_process_identity", identity)
    return observed


def _create_pending(marker_path: Path, monkeypatch) -> dict:
    _patch_pending_owner(monkeypatch)
    return supervised_runtime_mode.create_owner_bound_marker(
        OWNER_PID,
        launch_token=LAUNCH_TOKEN,
        runtime_revision=REVISION,
        path=marker_path,
    )


def _activate(marker_path: Path, tmp_path: Path, monkeypatch, *, now: int = 1000):
    _create_pending(marker_path, monkeypatch)
    processes = _patch_managed_processes(monkeypatch)
    receipt = tmp_path / "android-runtime-acceptance.json"
    receipt.write_text('{"status":"pass"}\n', encoding="utf-8")
    monkeypatch.setattr(supervised_runtime_mode, "RUNTIME_ACCEPTANCE_PATH", receipt)
    monkeypatch.setattr(supervised_runtime_mode.time, "time", lambda: now)
    marker = supervised_runtime_mode.activate_runtime_lease(
        launch_token=LAUNCH_TOKEN,
        runtime_revision=REVISION,
        path=marker_path,
    )
    return marker, processes, receipt


def test_preflight_arm_keeps_persisted_switches_off_and_preserves_config(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file)
    before = env_file.read_text(encoding="utf-8")

    result = pilot_runtime.preflight_arm(env_file)

    assert result["persisted_fail_safe"] is True
    assert result["persisted_allow_real_application_submit"] is False
    assert result["persisted_lever_supervised_pilot_enabled"] is False
    assert result["persisted_autopilot_enabled"] is False
    assert result["configuration_valid"] is True
    assert result["one_time_application_approval_still_required"] is True
    assert env_file.read_text(encoding="utf-8") == before


def test_preflight_arm_rejects_sensitive_conflicts_without_arming(tmp_path):
    env_file = tmp_path / ".env"
    cases = (
        ({"SECRET_KEY": "supersecretkey-change-in-production"}, "SECRET_KEY"),
        ({"ALLOW_REAL_FOLLOWUP_SEND": "true"}, "follow-up"),
        ({"GREENHOUSE_SUPERVISED_PILOT_ENABLED": "true"}, "Greenhouse"),
        ({"AUTOPILOT_ENABLED": "true"}, "AUTOPILOT_ENABLED"),
    )
    for overrides, pattern in cases:
        _write_env(env_file, **overrides)
        with pytest.raises(RuntimeError, match=pattern):
            pilot_runtime.preflight_arm(env_file)
        content = env_file.read_text(encoding="utf-8")
        assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in content
        assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in content


def test_persist_safe_forces_only_consequential_switches_off(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(
        env_file,
        ALLOW_REAL_APPLICATION_SUBMIT="true",
        LEVER_SUPERVISED_PILOT_ENABLED="true",
    )

    result = pilot_runtime.persist_safe(env_file)
    content = env_file.read_text(encoding="utf-8")

    assert result["persisted_fail_safe"] is True
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in content
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in content
    assert "CUSTOM_OPERATOR_SETTING=preserve-me" in content


def test_status_never_claims_unobserved_queue_or_final_submit(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    _write_env(env_file)
    monkeypatch.setattr(pilot_runtime, "DEFAULT_MARKER_PATH", tmp_path / "missing.json")

    result = pilot_runtime.status(env_file)

    assert result["persisted_fail_safe"] is True
    assert result["live_process_mode_observed"] is False
    assert result["live_submission_state_observed"] is False
    assert "submission_queued" not in result
    assert "final_submit_clicked" not in result


def test_pending_marker_is_non_authorizing_owner_token_revision_bound(tmp_path, monkeypatch):
    marker_path = tmp_path / "lease.json"
    observed = _patch_pending_owner(monkeypatch)

    marker = supervised_runtime_mode.create_owner_bound_marker(
        OWNER_PID,
        launch_token=LAUNCH_TOKEN,
        runtime_revision=REVISION,
        path=marker_path,
    )

    assert marker["state"] == supervised_runtime_mode.MARKER_STATE_PENDING
    assert marker["submission_approval_granted"] is False
    assert LAUNCH_TOKEN not in marker_path.read_text(encoding="utf-8")
    assert marker_path.stat().st_mode & 0o777 == 0o600
    assert supervised_runtime_mode.pending_runtime_marker_active(
        marker_path,
        expected_launch_token=LAUNCH_TOKEN,
        expected_revision=REVISION,
    ) is True
    assert supervised_runtime_mode.runtime_lease_status(marker_path)["active"] is False
    assert supervised_runtime_mode.pending_runtime_marker_active(
        marker_path,
        expected_launch_token=LAUNCH_TOKEN + "wrong",
        expected_revision=REVISION,
    ) is False
    assert supervised_runtime_mode.pending_runtime_marker_active(
        marker_path,
        expected_launch_token=LAUNCH_TOKEN,
        expected_revision="b" * 40,
    ) is False

    observed["owner_ticks"] += 1
    assert supervised_runtime_mode.pending_runtime_marker_active(
        marker_path,
        expected_launch_token=LAUNCH_TOKEN,
        expected_revision=REVISION,
    ) is False


def test_pending_marker_rejects_unrecognized_owner(tmp_path, monkeypatch):
    marker_path = tmp_path / "lease.json"
    monkeypatch.setattr(supervised_runtime_mode, "_process_start_ticks", lambda _pid: 123)
    monkeypatch.setattr(
        supervised_runtime_mode,
        "_process_cmdline",
        lambda _pid: "/data/data/com.termux/files/usr/bin/bash unrelated-script.sh",
    )

    with pytest.raises(RuntimeError, match="OWNER_IDENTITY_MISMATCH"):
        supervised_runtime_mode.create_owner_bound_marker(
            OWNER_PID,
            launch_token=LAUNCH_TOKEN,
            runtime_revision=REVISION,
            path=marker_path,
        )


def test_activation_binds_exact_processes_removes_shadow_receipt_and_hides_token(
    tmp_path, monkeypatch
):
    marker_path = tmp_path / "lease.json"
    marker, processes, receipt = _activate(marker_path, tmp_path, monkeypatch)

    assert marker["state"] == supervised_runtime_mode.MARKER_STATE_ACTIVE
    assert marker["processes"] == processes
    assert marker["submission_approval_granted"] is False
    assert receipt.exists() is False
    serialized = marker_path.read_text(encoding="utf-8")
    assert LAUNCH_TOKEN not in serialized
    assert json.loads(serialized)["launch_token_sha256"]
    status = supervised_runtime_mode.runtime_lease_status(
        marker_path,
        expected_launch_token=LAUNCH_TOKEN,
        expected_revision=REVISION,
    )
    assert status["active"] is True


def test_activation_fails_when_managed_process_identity_is_missing(tmp_path, monkeypatch):
    marker_path = tmp_path / "lease.json"
    _create_pending(marker_path, monkeypatch)
    monkeypatch.setattr(
        supervised_runtime_mode,
        "_pid_file_value",
        lambda path: API_PID if path.name == "api.pid" else WORKER_PID,
    )
    monkeypatch.setattr(
        supervised_runtime_mode,
        "_managed_process_identity",
        lambda role, pid, *, runtime_revision: None if role == "worker" else {
            "pid": API_PID,
            "start_ticks": 1,
            "cmdline_sha256": "1" * 64,
        },
    )

    with pytest.raises(RuntimeError, match="WORKER_IDENTITY_UNVERIFIED"):
        supervised_runtime_mode.activate_runtime_lease(
            launch_token=LAUNCH_TOKEN,
            runtime_revision=REVISION,
            path=marker_path,
        )


def test_active_lease_revokes_on_process_replacement_or_expiry(tmp_path, monkeypatch):
    marker_path = tmp_path / "lease.json"
    _marker, processes, _receipt = _activate(marker_path, tmp_path, monkeypatch, now=1000)

    assert supervised_runtime_mode.runtime_lease_status(marker_path)["active"] is True

    processes["worker"]["start_ticks"] += 1
    assert supervised_runtime_mode.runtime_lease_status(marker_path)["active"] is False
    processes["worker"]["start_ticks"] -= 1

    monkeypatch.setattr(supervised_runtime_mode.time, "time", lambda: 1000 + 3601)
    status = supervised_runtime_mode.runtime_lease_status(marker_path)
    assert status["active"] is False
    assert "lease_expired" in status["blockers"]


def test_runtime_lease_requires_current_bound_role_pid_and_revision(tmp_path, monkeypatch):
    marker_path = tmp_path / "lease.json"
    _marker, _processes, _receipt = _activate(marker_path, tmp_path, monkeypatch)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", REVISION)
    monkeypatch.setattr(supervised_runtime_mode.os, "getpid", lambda: WORKER_PID)
    original_ticks = supervised_runtime_mode._process_start_ticks
    monkeypatch.setattr(
        supervised_runtime_mode,
        "_process_start_ticks",
        lambda pid: 81002 if pid == WORKER_PID else original_ticks(pid),
    )

    assert supervised_runtime_mode.lever_supervised_runtime_lease_active(
        marker_path,
        required_role="worker",
    ) is True

    monkeypatch.setattr(supervised_runtime_mode.os, "getpid", lambda: 9999)
    assert supervised_runtime_mode.lever_supervised_runtime_lease_active(
        marker_path,
        required_role="worker",
    ) is False
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", "b" * 40)
    assert supervised_runtime_mode.lever_supervised_runtime_lease_active(
        marker_path,
        required_role="worker",
    ) is False


def test_cached_settings_stay_off_outside_exact_supervised_scopes(monkeypatch):
    settings = _safe_settings()
    monkeypatch.setattr(
        supervised_runtime_mode,
        "lever_supervised_runtime_lease_active",
        lambda *args, **kwargs: True,
    )

    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "api")
    monkeypatch.setattr(config_module, "_supervised_submission_service_on_stack", lambda: False)
    assert settings.allow_real_application_submit is False
    assert settings.lever_supervised_pilot_enabled is False

    monkeypatch.setattr(config_module, "_supervised_submission_service_on_stack", lambda: True)
    assert settings.allow_real_application_submit is True
    assert settings.lever_supervised_pilot_enabled is True

    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")
    assert settings.allow_real_application_submit is False
    with supervised_target_scope({"platform": "greenhouse"}):
        assert settings.allow_real_application_submit is False
    with supervised_target_scope({"platform": "lever", "posting_id": "abc"}):
        assert settings.allow_real_application_submit is True
        assert settings.lever_supervised_pilot_enabled is True


def test_final_lever_browser_verification_blocks_managed_worker_without_live_lease(
    monkeypatch,
):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")
    monkeypatch.setattr(
        supervised_target_identity,
        "lever_supervised_runtime_lease_active",
        lambda *args, **kwargs: False,
    )
    expected = {
        "platform": "lever",
        "adapter_version": "1.1.0",
        "site": "example",
        "posting_id": "abc-123",
        "region": "global",
        "posting_metadata_hash": "hash",
    }

    result = pytest.run(async_fn=None) if False else None
    import asyncio
    result = asyncio.run(
        supervised_target_identity.verify_supervised_browser_target(
            current_url="https://jobs.lever.co/example/abc-123/apply",
            adapter_name="lever",
            adapter_version="1.1.0",
            expected_metadata=expected,
            refresh_official_metadata=False,
        )
    )

    assert result["verified"] is False
    assert "lever_supervised_runtime_lease_inactive" in result["blockers"]


def test_native_wrapper_stages_pending_restart_then_process_bound_activation():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_pilot_wrapper.sh").read_text(
        encoding="utf-8"
    )
    installer = (
        BACKEND_ROOT / "scripts/install_android_native_browser_launcher.sh"
    ).read_text(encoding="utf-8")

    assert "run_pilot_mode persist-safe" in wrapper
    assert "run_pilot_mode preflight-arm" in wrapper
    assert "generate_launch_token" in wrapper
    assert "secrets.token_urlsafe(32)" in wrapper
    assert "create-marker --owner-pid" in wrapper
    assert "verify-marker --launch-token" in wrapper
    assert "activate-marker --launch-token" in wrapper
    assert "verify-active-marker --launch-token" in wrapper
    assert "promote_native_transition_marker" in wrapper
    assert "run_pilot_mode clear-marker" in wrapper
    assert "rollback_to_safe_mode" in wrapper
    assert "trap 'arm_exit $?' EXIT INT TERM HUP" in wrapper
    assert "run_stack_sanitized restart" in wrapper
    assert "unset JOBTOMATIK_OPERATIONS_ENV_FILE" in wrapper
    assert "unset JOBTOMATIK_LEVER_PILOT_LAUNCH_TOKEN" in wrapper
    assert "export AUTOPILOT_ENABLED=false" in wrapper
    assert "export ALLOW_REAL_APPLICATION_SUBMIT=false" in wrapper
    assert "export ALLOW_REAL_FOLLOWUP_SEND=false" in wrapper
    assert "export GREENHOUSE_SUPERVISED_PILOT_ENABLED=false" in wrapper
    assert "export LEVER_SUPERVISED_PILOT_ENABLED=false" in wrapper
    assert 'export JOBTOMATIK_LEVER_PILOT_LAUNCH_TOKEN="$launch_token"' not in wrapper
    assert "JOBTOMATIK_LEVER_PILOT_ARMED_EPHEMERAL" in wrapper
    assert "Persisted submit flags remain OFF" in wrapper
    assert "process-bound" in wrapper
    assert '"$STACK_COMMAND" stop || true' in wrapper

    assert 'PILOT_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_pilot_wrapper.sh"' in installer
    assert 'PILOT_DEST="$DEST_DIR/jobtomatik-pilot"' in installer
    assert 'install_atomically "$PILOT_SOURCE" "$PILOT_DEST"' in installer
