from __future__ import annotations

from pathlib import Path

import pytest

from scripts import lever_supervised_pilot_runtime as pilot_runtime


BACKEND_ROOT = Path(__file__).resolve().parents[1]


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
    assert result["ephemeral_runtime_overrides_required"] == {
        "ALLOW_REAL_APPLICATION_SUBMIT": True,
        "LEVER_SUPERVISED_PILOT_ENABLED": True,
        "ALLOW_REAL_FOLLOWUP_SEND": False,
        "AUTOPILOT_ENABLED": False,
    }
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


def test_native_pilot_wrapper_uses_ephemeral_arm_and_fail_safe_rollback_contract():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_pilot_wrapper.sh").read_text(
        encoding="utf-8"
    )
    installer = (
        BACKEND_ROOT / "scripts/install_android_native_browser_launcher.sh"
    ).read_text(encoding="utf-8")

    assert "run_pilot_mode persist-safe" in wrapper
    assert "run_pilot_mode preflight-arm" in wrapper
    assert "rollback_to_safe_mode" in wrapper
    assert "PENDING_MARKER" in wrapper
    assert "ACTIVE_MARKER" in wrapper
    assert "trap 'arm_exit $?' EXIT INT TERM HUP" in wrapper
    assert "JOBTOMATIK_SUPERVISED_LEVER_PILOT_RUNTIME=1" in wrapper
    assert '"$STACK_COMMAND" restart' in wrapper
    assert "JOBTOMATIK_LEVER_PILOT_ARMED_EPHEMERAL" in wrapper
    assert "Persisted submit flags remain OFF" in wrapper
    assert "One-time exact application approval is still required" in wrapper
    assert "run_pilot_mode persist-safe; then" in wrapper
    assert '"$STACK_COMMAND" stop || true' in wrapper
    assert "submission approval" not in wrapper.casefold()
    assert "queue" not in wrapper.casefold()
    assert "click submit" not in wrapper.casefold()

    assert 'PILOT_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_pilot_wrapper.sh"' in installer
    assert 'PILOT_DEST="$DEST_DIR/jobtomatik-pilot"' in installer
    assert 'install_atomically "$PILOT_SOURCE" "$PILOT_DEST"' in installer
