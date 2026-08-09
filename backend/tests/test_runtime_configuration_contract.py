from pathlib import Path

from app.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_compose_propagates_emergency_kill_switch_to_api_worker_and_beat():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert compose.count(
        "AUTOMATION_GLOBAL_KILL_SWITCH=${AUTOMATION_GLOBAL_KILL_SWITCH:-false}"
    ) == 3
    assert "\n      - GLOBAL_KILL_SWITCH=" not in compose


def test_compose_propagates_stale_attempt_recovery_threshold_to_all_runtime_roles():
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert compose.count(
        "AUTOPILOT_STALE_ATTEMPT_MINUTES=${AUTOPILOT_STALE_ATTEMPT_MINUTES:-30}"
    ) == 3
    assert "AUTOPILOT_STALE_ATTEMPT_MINUTES=30" in env_example


def test_phase11_workflow_uses_canonical_emergency_kill_switch_name():
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "full-stack-shadow-campaigns.yml"
    ).read_text(encoding="utf-8")

    assert 'AUTOMATION_GLOBAL_KILL_SWITCH: "false"' in workflow
    assert '\n  GLOBAL_KILL_SWITCH: "false"' not in workflow


def test_documented_environment_name_matches_core_settings_alias():
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    config = (REPO_ROOT / "backend" / "app" / "config.py").read_text(encoding="utf-8")

    assert "APP_ENV=development" in env_example
    assert 'AliasChoices("APP_ENV", "APP_ENVIRONMENT")' in config


def test_app_environment_field_name_remains_valid_for_direct_settings_construction():
    settings = Settings(_env_file=None, app_environment="test")

    assert settings.app_environment == "test"
