import os
from pathlib import Path
import subprocess

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/start_android_browser_cdp.sh",
        "scripts/jobtomatik_termux_wrapper.sh",
        "scripts/install_android_native_browser_launcher.sh",
        "scripts/manage_android_stack.sh",
    ],
)
def test_android_runtime_shell_script_has_valid_bash_syntax(relative_path):
    script = BACKEND_ROOT / relative_path
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_android_launcher_installer_copies_native_commands(tmp_path):
    prefix = tmp_path / "termux-prefix"
    destination = prefix / "bin"
    destination.mkdir(parents=True)

    environment = os.environ.copy()
    environment["JOBTOMATIK_TERMUX_PREFIX"] = str(prefix)

    subprocess.run(
        ["bash", str(BACKEND_ROOT / "scripts/install_android_native_browser_launcher.sh")],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    browser_command = destination / "jobtomatik-browser"
    stack_command = destination / "jobtomatik"
    assert browser_command.is_file()
    assert stack_command.is_file()
    assert os.access(browser_command, os.X_OK)
    assert os.access(stack_command, os.X_OK)
    assert "remote-debugging-port" in browser_command.read_text(encoding="utf-8")
    assert "proot-distro login" in stack_command.read_text(encoding="utf-8")


def test_termux_wrapper_does_not_assume_a_proot_storage_layout():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    assert "installed-rootfs" not in wrapper
    assert "containers/" not in wrapper
    assert "install_android_native_browser_launcher.sh" in wrapper
    assert "proot-distro login" in wrapper


def test_android_stack_manager_never_uses_broad_process_matching():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert "pkill" not in manager
    assert "killall" not in manager
    assert "stop_pid_file" in manager
    assert "UNMANAGED_PROCESS_OCCUPIES_8010" in manager


def test_android_worker_is_revisioned_and_consumes_all_runtime_queues():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'RUNTIME_REVISION="${JOBTOMATIK_RUNTIME_REVISION:-$(git -C "$REPO_ROOT" rev-parse HEAD' in manager
    assert 'jobtomatik-android-${RUNTIME_REVISION_SHORT}@%h' in manager
    assert "--pool=solo" in manager
    assert "--concurrency=1" in manager
    assert "-Q applications,celery,followup,scraping" in manager
    assert "WORKER_NODE_PREFIX" in manager


def test_android_worker_readiness_requires_real_application_queue_round_trip():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert "worker_application_canary_ready" in manager
    assert "application_queue_canary.apply_async" in manager
    assert 'queue="applications"' in manager
    assert "result.get(timeout=12" in manager
    assert "CELERY_APPLICATION_CANARY: READY" in manager


def test_android_managed_runtime_isolated_from_legacy_and_stale_managed_workers():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'ANDROID_REDIS_URL="${JOBTOMATIK_ANDROID_REDIS_URL:-redis://localhost:6379/1}"' in manager
    assert 'LEGACY_ANDROID_REDIS_URL="${JOBTOMATIK_LEGACY_ANDROID_REDIS_URL:-redis://localhost:6379/0}"' in manager
    assert 'set_env_value REDIS_URL "$ANDROID_REDIS_URL"' in manager
    assert 'export REDIS_URL="$ANDROID_REDIS_URL"' in manager
    assert '--broker "$LEGACY_ANDROID_REDIS_URL"' in manager
    assert '--broker "$ANDROID_REDIS_URL"' in manager
    assert '--mode managed' in manager
    assert "ANDROID_RUNTIME_BROKER: ISOLATED" in manager


def test_android_runtime_forces_nonblocking_automatic_application_entry():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert "set_env_value APPLICATION_TARGET_HUMAN_WAIT_SECONDS '0'" in manager
    assert "set_env_value APPLICATION_BROWSER_CDP_ENDPOINT 'http://127.0.0.1:9222'" in manager


def test_restart_preserves_browser_and_manager_performs_single_jobtomatik_tab_refresh():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'activate_stack()' in wrapper
    assert '"$BROWSER_COMMAND" start' in wrapper
    assert '"$BROWSER_COMMAND" restart' not in wrapper
    assert "refresh_frontend_tabs" not in wrapper
    assert "refresh_frontend_runtime" in manager
    assert "refresh_android_jobtomatik_tabs.py" in manager
    restart_case = wrapper.split("restart)", 1)[1].split(";;", 1)[0]
    assert "activate_stack restart" in restart_case


def test_android_update_always_fast_forwards_authoritative_main():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    assert "git fetch origin main" in wrapper
    assert "git switch main" in wrapper
    assert "git pull --ff-only origin main" in wrapper
    update_case = wrapper.split("update)", 1)[1].split(";;", 1)[0]
    assert "activate_stack restart" in update_case
