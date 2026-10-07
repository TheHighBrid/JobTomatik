"""Regression coverage for the OneHost production cutover contract."""

import os
from pathlib import Path
import subprocess

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.onehost-production.yml"
WRAPPER = ROOT / "backend/scripts/jobtomatik_termux_wrapper.sh"
CLIENT = ROOT / "frontend/src/api/client.js"


def _compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_onehost_production_has_no_beat_and_exactly_one_worker():
    data = _compose()
    services = data["services"]
    assert set(services) == {"db", "redis", "backend", "celery_worker"}
    worker = services["celery_worker"]
    command = " ".join(worker["command"])
    assert "--pool=solo" in command
    assert "--concurrency=1" in command
    assert "-m scripts.reconcile_onehost_startup" in command
    assert command.index("-m scripts.reconcile_onehost_startup") < command.index("exec celery")
    assert "celery beat" not in command.lower()


def test_onehost_worker_shares_api_network_pid_and_state_for_retained_browser():
    data = _compose()
    backend = data["services"]["backend"]
    worker = data["services"]["celery_worker"]
    assert worker["network_mode"] == "service:backend"
    assert worker["pid"] == "service:backend"
    assert "onehost_state:/state" in backend["volumes"]
    assert "onehost_state:/state" in worker["volumes"]
    for service in (backend, worker):
        env = service["environment"]
        assert env["APPLICATION_BROWSER_PROVIDER"] == "local"
        assert env["APPLICATION_BROWSER_CDP_ENDPOINT"] == ""
        assert env["APPLICATION_BROWSER_PROFILE_DIR"] == "/state/browser-profile"
        assert env["HANDOFF_STORAGE_DIR"] == "/state/handoffs"
        assert env["JOBTOMATIK_BROWSER_NODE_ID"] == "onehost-primary"


def test_onehost_worker_exposes_a_real_celery_healthcheck():
    """Verify the worker healthcheck requires a real Celery response."""
    data = _compose()
    worker = data["services"]["celery_worker"]
    healthcheck = worker["healthcheck"]
    command = " ".join(healthcheck["test"])
    assert "celery -A app.celery_app inspect ping" in command
    assert "grep -q pong" in command
    assert healthcheck["start_period"] == "20s"


def test_onehost_production_defaults_keep_real_actions_closed():
    data = _compose()
    env = data["services"]["backend"]["environment"]
    assert env["ALLOW_REAL_APPLICATION_SUBMIT"].endswith(":-false}")
    assert env["GREENHOUSE_SUPERVISED_PILOT_ENABLED"].endswith(":-false}")
    assert env["LEVER_SUPERVISED_PILOT_ENABLED"].endswith(":-false}")
    assert env["ALLOW_REAL_FOLLOWUP_SEND"].endswith(":-false}")
    assert env["AUTOPILOT_ENABLED"].endswith(":-false}")


def test_android_supported_runtime_actions_exit_before_legacy_server_path(tmp_path):
    environment = os.environ.copy()
    environment["HOME"] = str(tmp_path)
    environment["JOBTOMATIK_ANDROID_RUNTIME_DIR"] = str(tmp_path / "runtime")
    for action in ("start", "restart", "status"):
        completed = subprocess.run(
            ["bash", str(WRAPPER), action],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        output = completed.stdout + completed.stderr
        assert completed.returncode == 0, output
        assert f"JOBTOMATIK_ANDROID_THIN_CLIENT_MODE action={action}" in output
        assert "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED" not in output
        assert "proot-distro" not in output


def test_android_browser_acceptance_commands_are_explicitly_retired(tmp_path):
    environment = os.environ.copy()
    environment["HOME"] = str(tmp_path)
    environment["JOBTOMATIK_ANDROID_RUNTIME_DIR"] = str(tmp_path / "runtime")
    for action, marker in (
        ("browser-preflight", "JOBTOMATIK_ANDROID_BROWSER_PREFLIGHT_RETIRED"),
        ("acceptance", "JOBTOMATIK_ANDROID_RUNTIME_ACCEPTANCE_RETIRED"),
    ):
        completed = subprocess.run(
            ["bash", str(WRAPPER), action],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        output = completed.stdout + completed.stderr
        assert completed.returncode == 2, output
        assert "JOBTOMATIK_ANDROID_THIN_CLIENT_MODE" in output
        assert marker in output
        assert "ANDROID_NATIVE_CHROME_DEVICE_REQUIRED" not in output


def test_android_client_preserves_operator_selected_remote_api():
    source = CLIENT.read_text(encoding="utf-8")
    assert "jobtomatik_api_url" in source
    assert "safeLocalStorage.getItem(API_URL_STORAGE_KEY)" in source
    assert "saved || DEFAULT_API_URL" in source
    assert "setApiBaseUrl" in source
