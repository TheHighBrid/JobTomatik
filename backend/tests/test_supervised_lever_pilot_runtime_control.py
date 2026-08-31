from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.services import supervised_runtime_mode
from scripts import lever_supervised_pilot_runtime as pilot_runtime


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40
LAUNCH_TOKEN = "restart-capability-token-" + ("x" * 40)


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


def test_preflight_arm_keeps_persisted_submit_switches_off_and_preserves_config(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file)

    before = env_file.read_text(encoding="utf-8")
    result = pilot_runtime.preflight_arm(env_file)
    after = env_file.read_text(encoding="utf-8")

    assert result["persisted_fail_safe"] is True
    assert result["persisted_allow_real_application_submit"] is False
    assert result["persisted_lever_supervised_pilot_enabled"] is False
    assert result["persisted_autopilot_enabled"] is False
    assert result["configuration_valid"] is True
    assert result["secret_key_safe_for_sensitive_runtime"] is True
    assert result["one_time_application_approval_still_required"] is True
    assert result["live_process_mode_observed"] is False
    assert result["live_submission_state_observed"] is False
    assert result["ephemeral_runtime_marker_required"] is True
    assert len(result["runtime_revision"]) == 40
    assert after == before
    assert "CUSTOM_OPERATOR_SETTING=preserve-me" in after
    assert "REDIS_URL=redis://localhost:6379/1" in after


def test_preflight_arm_rejects_placeholder_secret_without_enabling_any_switch(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file, SECRET_KEY="supersecretkey-change-in-production")

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        pilot_runtime.preflight_arm(env_file)

    content = env_file.read_text(encoding="utf-8")
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in content
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in content


def test_preflight_arm_rejects_followup_other_platform_and_autopilot_conflicts(tmp_path):
    env_file = tmp_path / ".env"

    _write_env(env_file, ALLOW_REAL_FOLLOWUP_SEND="true")
    with pytest.raises(RuntimeError, match="follow-up"):
        pilot_runtime.preflight_arm(env_file)
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in env_file.read_text(encoding="utf-8")

    _write_env(env_file, GREENHOUSE_SUPERVISED_PILOT_ENABLED="true")
    with pytest.raises(RuntimeError, match="Greenhouse"):
        pilot_runtime.preflight_arm(env_file)
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in env_file.read_text(encoding="utf-8")

    _write_env(env_file, AUTOPILOT_ENABLED="true")
    with pytest.raises(RuntimeError, match="AUTOPILOT_ENABLED"):
        pilot_runtime.preflight_arm(env_file)
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in env_file.read_text(encoding="utf-8")
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in env_file.read_text(encoding="utf-8")


def test_persist_safe_forces_consequential_switches_off_without_parsing_unrelated_settings(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(
        env_file,
        ALLOW_REAL_APPLICATION_SUBMIT="true",
        LEVER_SUPERVISED_PILOT_ENABLED="true",
    )

    result = pilot_runtime.persist_safe(env_file)
    content = env_file.read_text(encoding="utf-8")

    assert result["persisted_fail_safe"] is True
    assert result["persisted_allow_real_application_submit"] is False
    assert result["persisted_lever_supervised_pilot_enabled"] is False
    assert result["live_process_mode_observed"] is False
    assert result["live_submission_state_observed"] is False
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in content
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in content
    assert "CUSTOM_OPERATOR_SETTING=preserve-me" in content


def test_target_key_duplicates_are_collapsed_deterministically_by_safe_persist(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SECRET_KEY=" + ("s" * 48) + "\n"
        "ALLOW_REAL_APPLICATION_SUBMIT=false\n"
        "ALLOW_REAL_APPLICATION_SUBMIT=true\n"
        "ALLOW_REAL_FOLLOWUP_SEND=false\n"
        "GREENHOUSE_SUPERVISED_PILOT_ENABLED=false\n"
        "LEVER_SUPERVISED_PILOT_ENABLED=false\n"
        "LEVER_SUPERVISED_PILOT_ENABLED=true\n"
        "AUTOPILOT_ENABLED=false\n",
        encoding="utf-8",
    )

    pilot_runtime.persist_safe(env_file)
    content = env_file.read_text(encoding="utf-8")

    assert content.count("ALLOW_REAL_APPLICATION_SUBMIT=") == 1
    assert content.count("LEVER_SUPERVISED_PILOT_ENABLED=") == 1
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in content
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in content


def test_status_does_not_claim_unobserved_queue_or_submit_outcomes(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file)

    result = pilot_runtime.status(env_file)

    assert result["persisted_fail_safe"] is True
    assert result["live_process_mode_observed"] is False
    assert result["live_submission_state_observed"] is False
    assert "submission_queued" not in result
    assert "final_submit_clicked" not in result


def _patch_owner_identity(monkeypatch, *, owner_pid: int, parent_pid: int, observed: dict):
    def process_ticks(pid: int):
        return observed["owner_ticks"] if pid == owner_pid else None

    def process_cmdline(pid: int):
        if pid == owner_pid:
            return observed["owner_cmdline"]
        if pid == parent_pid:
            return observed["parent_cmdline"]
        return ""

    monkeypatch.setattr(supervised_runtime_mode, "_process_start_ticks", process_ticks)
    monkeypatch.setattr(supervised_runtime_mode, "_process_cmdline", process_cmdline)


def test_owner_bound_runtime_marker_expires_on_owner_token_or_revision_change(tmp_path, monkeypatch):
    marker_path = tmp_path / "lever-supervised-pilot-runtime.json"
    owner_pid = 4242
    parent_pid = 5151
    observed = {
        "owner_ticks": 123456,
        "owner_cmdline": "/data/data/com.termux/files/usr/bin/bash /data/data/com.termux/files/usr/bin/jobtomatik-pilot arm",
        "parent_cmdline": "bash -c source backend/scripts/manage_android_stack.sh restart",
    }
    _patch_owner_identity(
        monkeypatch,
        owner_pid=owner_pid,
        parent_pid=parent_pid,
        observed=observed,
    )

    marker = supervised_runtime_mode.create_owner_bound_marker(
        owner_pid,
        launch_token=LAUNCH_TOKEN,
        runtime_revision=REVISION,
        path=marker_path,
    )
    assert marker["submission_approval_granted"] is False
    assert marker["owner_cmdline_token"] == "jobtomatik-pilot"
    assert marker["runtime_revision"] == REVISION
    assert "launch_token_sha256" in marker
    assert LAUNCH_TOKEN not in marker_path.read_text(encoding="utf-8")
    assert supervised_runtime_mode.lever_supervised_runtime_marker_active(
        marker_path,
        expected_launch_token=LAUNCH_TOKEN,
        expected_revision=REVISION,
    ) is True
    assert marker_path.stat().st_mode & 0o777 == 0o600

    assert supervised_runtime_mode.lever_supervised_runtime_marker_active(
        marker_path,
        expected_launch_token=LAUNCH_TOKEN + "wrong",
        expected_revision=REVISION,
    ) is False
    assert supervised_runtime_mode.lever_supervised_runtime_marker_active(
        marker_path,
        expected_launch_token=LAUNCH_TOKEN,
        expected_revision="b" * 40,
    ) is False

    observed["owner_ticks"] += 1
    assert supervised_runtime_mode.lever_supervised_runtime_marker_active(
        marker_path,
        expected_launch_token=LAUNCH_TOKEN,
        expected_revision=REVISION,
    ) is False

    supervised_runtime_mode.clear_owner_bound_marker(marker_path)
    assert marker_path.exists() is False


def test_owner_bound_runtime_marker_rejects_unrecognized_creator(tmp_path, monkeypatch):
    marker_path = tmp_path / "lever-supervised-pilot-runtime.json"
    monkeypatch.setattr(supervised_runtime_mode, "_process_start_ticks", lambda _pid: 123)
    monkeypatch.setattr(
        supervised_runtime_mode,
        "_process_cmdline",
        lambda _pid: "/data/data/com.termux/files/usr/bin/bash unrelated-script.sh",
    )

    with pytest.raises(RuntimeError, match="OWNER_IDENTITY_MISMATCH"):
        supervised_runtime_mode.create_owner_bound_marker(
            77,
            launch_token=LAUNCH_TOKEN,
            runtime_revision=REVISION,
            path=marker_path,
        )
    assert marker_path.exists() is False


def test_managed_runtime_capability_requires_exact_parent_token_role_and_revision(tmp_path, monkeypatch):
    marker_path = tmp_path / "lever-supervised-pilot-runtime.json"
    owner_pid = 4242
    parent_pid = 5151
    observed = {
        "owner_ticks": 123456,
        "owner_cmdline": "/data/data/com.termux/files/usr/bin/bash /data/data/com.termux/files/usr/bin/jobtomatik-pilot arm",
        "parent_cmdline": "bash -c source backend/scripts/manage_android_stack.sh restart",
        "parent_env": {
            "JOBTOMATIK_RUNTIME_MODE": "android_managed",
            "JOBTOMATIK_FRONTEND_RUNTIME_MODE": "static_artifact",
            "JOBTOMATIK_LEVER_PILOT_LAUNCH_TOKEN": LAUNCH_TOKEN,
        },
    }
    _patch_owner_identity(
        monkeypatch,
        owner_pid=owner_pid,
        parent_pid=parent_pid,
        observed=observed,
    )
    monkeypatch.setattr(supervised_runtime_mode.os, "getppid", lambda: parent_pid)
    monkeypatch.setattr(
        supervised_runtime_mode,
        "_process_environ",
        lambda pid: dict(observed["parent_env"]) if pid == parent_pid else {},
    )
    supervised_runtime_mode.create_owner_bound_marker(
        owner_pid,
        launch_token=LAUNCH_TOKEN,
        runtime_revision=REVISION,
        path=marker_path,
    )
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", REVISION)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", REVISION)

    assert supervised_runtime_mode.managed_android_lever_runtime_capability_active(marker_path) is True

    observed["parent_env"]["JOBTOMATIK_LEVER_PILOT_LAUNCH_TOKEN"] = LAUNCH_TOKEN + "wrong"
    assert supervised_runtime_mode.managed_android_lever_runtime_capability_active(marker_path) is False
    observed["parent_env"]["JOBTOMATIK_LEVER_PILOT_LAUNCH_TOKEN"] = LAUNCH_TOKEN

    observed["parent_cmdline"] = "bash unrelated-script.sh"
    assert supervised_runtime_mode.managed_android_lever_runtime_capability_active(marker_path) is False
    observed["parent_cmdline"] = "bash -c source backend/scripts/manage_android_stack.sh restart"

    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "frontend")
    assert supervised_runtime_mode.managed_android_lever_runtime_capability_active(marker_path) is False
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "api")

    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", "b" * 40)
    assert supervised_runtime_mode.managed_android_lever_runtime_capability_active(marker_path) is False


def _settings_with_safe_inputs() -> Settings:
    return Settings(
        _env_file=None,
        secret_key="s" * 48,
        allow_real_application_submit=False,
        allow_real_followup_send=False,
        greenhouse_supervised_pilot_enabled=False,
        lever_supervised_pilot_enabled=False,
    )


def test_settings_elevates_only_when_verified_managed_capability_is_active(monkeypatch):
    monkeypatch.setattr(
        supervised_runtime_mode,
        "managed_android_lever_runtime_capability_active",
        lambda: False,
    )
    safe = _settings_with_safe_inputs()
    assert safe.allow_real_application_submit is False
    assert safe.lever_supervised_pilot_enabled is False

    monkeypatch.setattr(
        supervised_runtime_mode,
        "managed_android_lever_runtime_capability_active",
        lambda: True,
    )
    managed = _settings_with_safe_inputs()
    assert managed.allow_real_application_submit is True
    assert managed.lever_supervised_pilot_enabled is True


def test_native_pilot_wrapper_uses_exact_restart_token_sanitized_env_and_fail_safe_rollback():
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
    assert "--launch-token" in wrapper
    assert "verify_runtime_marker" in wrapper
    assert "run_pilot_mode clear-marker" in wrapper
    assert "clear_runtime_marker_or_contain" in wrapper
    assert "rollback_to_safe_mode" in wrapper
    assert "PENDING_MARKER" in wrapper
    assert "ACTIVE_MARKER" in wrapper
    assert "trap 'arm_exit $?' EXIT INT TERM HUP" in wrapper
    assert "JOBTOMATIK_SUPERVISED_LEVER_PILOT_RUNTIME=1" not in wrapper
    assert "run_stack_sanitized restart" in wrapper
    assert "unset JOBTOMATIK_OPERATIONS_ENV_FILE" in wrapper
    assert "unset JOBTOMATIK_LEVER_PILOT_LAUNCH_TOKEN" in wrapper
    assert "export AUTOPILOT_ENABLED=false" in wrapper
    assert "export ALLOW_REAL_APPLICATION_SUBMIT=false" in wrapper
    assert "export ALLOW_REAL_FOLLOWUP_SEND=false" in wrapper
    assert "export GREENHOUSE_SUPERVISED_PILOT_ENABLED=false" in wrapper
    assert "export LEVER_SUPERVISED_PILOT_ENABLED=false" in wrapper
    assert 'export JOBTOMATIK_LEVER_PILOT_LAUNCH_TOKEN="$launch_token"' in wrapper
    assert "JOBTOMATIK_LEVER_PILOT_ARMED_EPHEMERAL" in wrapper
    assert "Persisted submit flags remain OFF" in wrapper
    assert "One-time exact application approval is still required" in wrapper
    assert '"$STACK_COMMAND" stop || true' in wrapper
    assert "submission approval" not in wrapper.casefold()
    assert "queue" not in wrapper.casefold()
    assert "click submit" not in wrapper.casefold()

    assert 'PILOT_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_pilot_wrapper.sh"' in installer
    assert 'PILOT_DEST="$DEST_DIR/jobtomatik-pilot"' in installer
    assert 'install_atomically "$PILOT_SOURCE" "$PILOT_DEST"' in installer
