from __future__ import annotations

from scripts import lever_supervised_pilot_runtime as pilot_runtime


def test_persist_safe_clears_autopilot_and_preserves_unrelated_config(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SECRET_KEY=" + ("s" * 48) + "\n"
        "ALLOW_REAL_APPLICATION_SUBMIT=true\n"
        "LEVER_SUPERVISED_PILOT_ENABLED=true\n"
        "AUTOPILOT_ENABLED=true\n"
        "ALLOW_REAL_FOLLOWUP_SEND=false\n"
        "GREENHOUSE_SUPERVISED_PILOT_ENABLED=false\n"
        "CUSTOM_OPERATOR_SETTING=preserve-me\n",
        encoding="utf-8",
    )

    result = pilot_runtime.persist_safe(env_file)
    content = env_file.read_text(encoding="utf-8")

    assert result["persisted_fail_safe"] is True
    assert result["persisted_allow_real_application_submit"] is False
    assert result["persisted_lever_supervised_pilot_enabled"] is False
    assert result["persisted_autopilot_enabled"] is False
    assert "ALLOW_REAL_APPLICATION_SUBMIT=false" in content
    assert "LEVER_SUPERVISED_PILOT_ENABLED=false" in content
    assert "AUTOPILOT_ENABLED=false" in content
    assert "CUSTOM_OPERATOR_SETTING=preserve-me" in content

    preflight = pilot_runtime.preflight_arm(env_file)
    assert preflight["persisted_fail_safe"] is True
    assert preflight["persisted_autopilot_enabled"] is False
    assert preflight["configuration_valid"] is True
