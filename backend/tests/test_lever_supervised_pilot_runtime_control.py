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


def test_arm_enables_only_supervised_lever_switches_and_preserves_unrelated_config(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file)

    status = pilot_runtime.arm(env_file)
    content = env_file.read_text(encoding="utf-8")

    assert status["lever_supervised_armed"] is True
    assert status["allow_real_application_submit"] is True
    assert status["lever_supervised_pilot_enabled"] is True
    assert status["greenhouse_supervised_pilot_enabled"] is False
    assert status["allow_real_followup_send"] is False
    assert status["one_time_application_approval_still_required"] is True
    assert status["submission_queued"] is False
    assert status["final_submit_clicked"] is False
    assert "CUSTOM_OPERATOR_SETTING=preserve-me" in content
    assert "REDIS_URL=redis://localhost:6379/1" in content
    assert content.count("ALLOW_REAL_APPLICATION_SUBMIT=") == 1
    assert content.count("LEVER_SUPERVISED_PILOT_ENABLED=") == 1


def test_arm_rejects_placeholder_secret_without_enabling_any_switch(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file, SECRET_KEY="supersecretkey-change-in-production")

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        pilot_runtime.arm(env_file)

    content = env_file.read_text(encoding="utf-8")
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in content
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in content


def test_arm_rejects_followup_sending_and_other_platform_pilot(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(env_file, ALLOW_REAL_FOLLOWUP_SEND="true")
    with pytest.raises(RuntimeError, match="follow-up"):
        pilot_runtime.arm(env_file)
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in env_file.read_text(encoding="utf-8")

    _write_env(env_file, GREENHOUSE_SUPERVISED_PILOT_ENABLED="true")
    with pytest.raises(RuntimeError, match="Greenhouse"):
        pilot_runtime.arm(env_file)
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in env_file.read_text(encoding="utf-8")


def test_disarm_persists_safe_switches_off(tmp_path):
    env_file = tmp_path / ".env"
    _write_env(
        env_file,
        ALLOW_REAL_APPLICATION_SUBMIT="true",
        LEVER_SUPERVISED_PILOT_ENABLED="true",
    )

    status = pilot_runtime.disarm(env_file)

    assert status["lever_supervised_armed"] is False
    assert status["allow_real_application_submit"] is False
    assert status["lever_supervised_pilot_enabled"] is False
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in env_file.read_text(encoding="utf-8")
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in env_file.read_text(encoding="utf-8")


def test_target_key_duplicates_are_collapsed_deterministically(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SECRET_KEY=" + ("s" * 48) + "\n"
        "ALLOW_REAL_APPLICATION_SUBMIT=false\n"
        "ALLOW_REAL_APPLICATION_SUBMIT=true\n"
        "ALLOW_REAL_FOLLOWUP_SEND=false\n"
        "GREENHOUSE_SUPERVISED_PILOT_ENABLED=false\n"
        "LEVER_SUPERVISED_PILOT_ENABLED=false\n"
        "LEVER_SUPERVISED_PILOT_ENABLED=true\n",
        encoding="utf-8",
    )

    pilot_runtime.disarm(env_file)
    content = env_file.read_text(encoding="utf-8")

    assert content.count("ALLOW_REAL_APPLICATION_SUBMIT=") == 1
    assert content.count("LEVER_SUPERVISED_PILOT_ENABLED=") == 1
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in content
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in content


def test_native_pilot_wrapper_rolls_back_failed_arm_and_never_grants_application_approval():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_pilot_wrapper.sh").read_text(
        encoding="utf-8"
    )
    installer = (
        BACKEND_ROOT / "scripts/install_android_native_browser_launcher.sh"
    ).read_text(encoding="utf-8")

    assert "run_pilot_mode arm" in wrapper
    assert "rollback_to_safe_mode" in wrapper
    assert "run_pilot_mode disarm" in wrapper
    assert '"$STACK_COMMAND" restart' in wrapper
    assert "run_pilot_mode verify-armed" in wrapper
    assert "run_pilot_mode verify-disarmed" in wrapper
    assert "JOBTOMATIK_LEVER_PILOT_ARMED" in wrapper
    assert "One-time exact application approval is still required" in wrapper
    assert "submission approval" not in wrapper.casefold()
    assert "queue" not in wrapper.casefold()
    assert "click submit" not in wrapper.casefold()

    assert 'PILOT_SOURCE="$BACKEND_ROOT/scripts/jobtomatik_pilot_wrapper.sh"' in installer
    assert 'PILOT_DEST="$DEST_DIR/jobtomatik-pilot"' in installer
    assert 'install_atomically "$PILOT_SOURCE" "$PILOT_DEST"' in installer
