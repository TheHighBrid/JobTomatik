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
        "scripts/jobtomatik_process_identity.sh",
        "scripts/sanitize_android_runtime_pid_files.sh",
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
    identity_helper = destination / "jobtomatik_process_identity.sh"
    assert browser_command.is_file()
    assert stack_command.is_file()
    assert identity_helper.is_file()
    assert os.access(browser_command, os.X_OK)
    assert os.access(stack_command, os.X_OK)
    assert os.access(identity_helper, os.X_OK)
    assert "remote-debugging-port" in browser_command.read_text(encoding="utf-8")
    assert "proot-distro login" in stack_command.read_text(encoding="utf-8")
    assert "jobtomatik_signal_if_identity" in identity_helper.read_text(encoding="utf-8")


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


def test_android_native_wrapper_sanitizes_pid_files_before_manager_signals():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    sanitizer = (
        BACKEND_ROOT / "scripts/sanitize_android_runtime_pid_files.sh"
    ).read_text(encoding="utf-8")

    assert "sanitize_runtime_pid_files" in wrapper
    assert "sanitize_android_runtime_pid_files.sh" in wrapper
    assert "supervisor_identity_matches" in wrapper
    assert "jobtomatik_signal_if_identity" in wrapper
    assert "ANDROID_STALE_PID_REJECTED" in sanitizer
    assert "pid_file_removed_process_not_signaled" in sanitizer


def test_android_browser_supervisor_requires_identity_before_signal():
    browser = (BACKEND_ROOT / "scripts/start_android_browser_cdp.sh").read_text(
        encoding="utf-8"
    )

    assert "supervisor_identity_matches" in browser
    assert "jobtomatik_signal_if_identity" in browser
    assert "ANDROID_BROWSER_STALE_SUPERVISOR_PID_REJECTED" in browser


def test_android_browser_defaults_to_verification_compatible_graphics():
    browser = (BACKEND_ROOT / "scripts/start_android_browser_cdp.sh").read_text(
        encoding="utf-8"
    )
    command = browser.split("browser_command() {", 1)[1].split("\n}\n", 1)[0]

    assert 'GRAPHICS_MODE="${JOBTOMATIK_ANDROID_BROWSER_GRAPHICS_MODE:-verification}"' in browser
    assert 'local -a graphics_args=(--disable-features=Vulkan,WebGPU)' in command
    assert 'graphics_args=(--disable-gpu --disable-features=Vulkan,WebGPU)' in command
    assert 'verification)' in command
    assert 'safe)' in command
    assert '"${graphics_args[@]}"' in command
    assert "ANDROID_BROWSER_INVALID_GRAPHICS_MODE" in command


def test_android_browser_recycles_only_managed_graphics_contract_drift():
    browser = (BACKEND_ROOT / "scripts/start_android_browser_cdp.sh").read_text(
        encoding="utf-8"
    )
    start_case = browser.split("  start)\n", 1)[1].rsplit("\nesac", 1)[0]

    assert "process_has_exact_token" in browser
    assert "browser_graphics_contract_matches" in browser
    assert "managed_browser_graphics_contract_ready" in browser
    assert 'process_has_exact_token "$pid" "--disable-gpu"' in browser
    assert "ANDROID_BROWSER_LAUNCH_CONTRACT_CHANGED" in start_case
    assert 'contract_status=0' in start_case
    assert '"$SCRIPT_PATH" stop' in start_case
    assert "ANDROID_BROWSER_CDP_CONNECTED_UNMANAGED_PRESERVED" in start_case


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


def test_android_worker_readiness_requires_one_persisted_application_queue_round_trip():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'WORKER_CANARY_RECEIPT_FILE="$RUNTIME_DIR/celery-application-canary.json"' in manager
    assert "worker_application_canary_probe" in manager
    assert "worker_application_canary_receipt_ready" in manager
    assert "application_queue_canary.apply_async" in manager
    assert 'queue="applications"' in manager
    assert "result.get(timeout=60" in manager
    assert "write_worker_canary_receipt" in manager
    assert "validate_worker_canary_receipt" in manager
    assert "CELERY_APPLICATION_CANARY: READY" in manager
    assert "source=startup_receipt" in manager


def test_android_managed_runtime_requires_phase12_attestation_for_api_worker_and_beat():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'EXPECTED_RUNTIME_REVISION="${JOBTOMATIK_EXPECTED_REVISION:-$RUNTIME_REVISION}"' in manager
    assert "scripts/check_runtime_identity.py --require-attested" in manager
    assert "JOBTOMATIK_RUNTIME_ROLE=api" in manager
    assert "JOBTOMATIK_RUNTIME_ROLE=worker" in manager
    assert "JOBTOMATIK_RUNTIME_ROLE=beat" in manager
    assert "/api/system/runtime-identity" in manager
    assert 'payload.get("role") == "api"' in manager
    assert 'payload.get("runtime_role") != "worker"' in manager
    assert 'payload.get("role") == "beat"' in manager
    assert 'payload.get("deployment_attested") is not True' in manager
    assert "ANDROID_RUNTIME_ATTESTATION: READY" in manager


def test_android_managed_runtime_processes_do_not_inherit_safety_settings():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    for function_name in ("start_api", "start_worker", "start_beat"):
        section = manager.split(f"{function_name}() {{", 1)[1].split("\n}\n", 1)[0]
        assert "nohup env -i" in section
        assert 'PATH="$PATH"' in section
        assert "JOBTOMATIK_RUNTIME_ROLE=" in section


def test_android_managed_runtime_supervises_shadow_recovery_beat():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'BEAT_PID_FILE="$RUNTIME_DIR/celery-beat.pid"' in manager
    assert 'BEAT_IDENTITY_FILE="$RUNTIME_DIR/celery-beat-identity.json"' in manager
    assert 'BEAT_SCHEDULE="$RUNTIME_DIR/celerybeat-schedule"' in manager
    assert "beat_schedule_contract_ready" in manager
    assert '"recover-stalled-shadow-campaigns"' in manager
    assert '"app.tasks.shadow_runs.recover_stalled_shadow_sessions"' in manager
    assert "{11, 26, 41, 56}" in manager
    assert '--schedule="$BEAT_SCHEDULE"' in manager
    assert "start_beat" in manager
    assert "CELERY_BEAT: READY_ATTESTED" in manager
    assert 'stop_pid_file "$BEAT_PID_FILE"' in manager


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
    assert 'set_env_value APPLICATION_BROWSER_CDP_ENDPOINT "${contract[1]}"' in manager
    assert 'set_env_value APPLICATION_BROWSER_PROVIDER "${contract[0]}"' in manager


def test_android_manager_does_not_shell_source_the_secrets_env_file():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'source "$ENV_FILE"' not in manager
    assert '. "$ENV_FILE"' not in manager


def test_restart_preserves_browser_and_manager_performs_single_jobtomatik_tab_refresh():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'activate_stack()' in wrapper
    assert 'ensure_application_browser_endpoint' in wrapper
    assert '"$BROWSER_COMMAND" start' not in wrapper
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
    executable_update_case = "\n".join(
        line for line in update_case.splitlines() if not line.lstrip().startswith("#")
    )
    assert "activate_stack restart" not in executable_update_case
    assert "JOBTOMATIK_ANDROID_LAUNCHER_REEXECUTING" in executable_update_case
    assert 'exec "${JOBTOMATIK_STACK_COMMAND:-$0}" restart' in executable_update_case


def test_android_update_syncs_and_attests_backend_environment_before_reexec():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    update_case = wrapper.split("  update)\n", 1)[1].split("    ;;", 1)[0]

    assert "verify_python_environment_requirements.py" in wrapper
    assert "pip install --disable-pip-version-check -r backend/requirements.txt" in wrapper
    assert update_case.index("update_main") < update_case.index("sync_backend_environment")
    assert update_case.index("sync_backend_environment") < update_case.index("install_native_commands")
    assert update_case.index("install_native_commands") < update_case.index("exec ")


def test_deployment_restart_propagates_one_bounded_legacy_endpoint_migration():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    installer = (
        BACKEND_ROOT / "scripts/install_android_native_browser_launcher.sh"
    ).read_text(encoding="utf-8")
    consume = wrapper.split("consume_deployment_restart_marker() {", 1)[1].split(
        "\n}\n", 1
    )[0]

    assert 'touch "$DEPLOYMENT_RESTART_MARKER"' in installer
    assert '[[ -f "$DEPLOYMENT_RESTART_MARKER" ]]' in consume
    assert "export JOBTOMATIK_MIGRATE_LEGACY_BROWSER_ENDPOINT=1" in consume
    assert "JOBTOMATIK_MIGRATE_LEGACY_BROWSER_ENDPOINT='$migration_flag'" in wrapper
    assert 'rm -f "$DEPLOYMENT_RESTART_MARKER"' in consume


def test_standalone_acceptance_revalidates_selected_adb_device_binding():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    acceptance_case = wrapper.split("  acceptance)\n", 1)[1].split("    ;;", 1)[0]

    assert "ensure_application_browser_endpoint" in acceptance_case
    assert acceptance_case.index("ensure_application_browser_endpoint") < (
        acceptance_case.index("run_runtime_acceptance")
    )


def test_runtime_acceptance_runs_from_backend_config_root():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )
    function = wrapper.split("run_runtime_acceptance() {", 1)[1].split("\n}\n", 1)[0]

    assert "cd '$PROOT_REPO/backend'" in function
    assert ".venv/bin/python scripts/android_runtime_acceptance.py" in function
    assert "cd '$PROOT_REPO';" not in function
    assert "backend/.venv/bin/python backend/scripts/android_runtime_acceptance.py" not in function


def test_android_manager_invokes_browser_contract_as_backend_module():
    manager = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert (
        '"$VENV/bin/python" -m scripts.application_browser_contract identity'
        in manager
    )
    assert (
        '"$VENV/bin/python" -m scripts.application_browser_contract config'
        in manager
    )
    assert "$BACKEND_ROOT/scripts/application_browser_contract.py" not in manager


def test_runtime_sensitive_actions_fail_closed_on_python_environment_drift():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    for action in ("start", "restart", "status", "acceptance"):
        section = wrapper.split(f"  {action})\n", 1)[1].split("    ;;", 1)[0]
        assert "verify_backend_environment" in section
