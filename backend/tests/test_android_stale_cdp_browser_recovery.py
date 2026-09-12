import os
from pathlib import Path
import subprocess
import time


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh"
BROWSER = BACKEND_ROOT / "scripts/start_android_browser_cdp.sh"
INSTALLER = BACKEND_ROOT / "scripts/install_android_native_browser_launcher.sh"


def _function_body(source: str, name: str) -> str:
    marker = f"{name}() {{"
    start = source.index(marker)
    tail = source[start + len(marker) :]
    end = tail.index("\n}\n")
    return tail[:end]


def _alive(process: subprocess.Popen) -> bool:
    return process.poll() is None


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _spawn_fake_owned_browser(*, profile: Path, port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "bash",
            "-c",
            "trap 'exit 0' TERM INT HUP; while :; do sleep 1; done",
            "jobtomatik-test-browser",
            f"--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
        ]
    )


def _browser_env(*, runtime_dir: Path, profile: Path, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "JOBTOMATIK_ANDROID_RUNTIME_DIR": str(runtime_dir),
            "JOBTOMATIK_ANDROID_BROWSER_PROFILE": str(profile),
            "JOBTOMATIK_ANDROID_BROWSER_BIN": "/bin/true",
            "JOBTOMATIK_ANDROID_BROWSER_PORT": str(port),
        }
    )
    return env


def test_android_wrapper_proves_real_playwright_before_proot_stack_start():
    source = WRAPPER.read_text(encoding="utf-8")
    activate = _function_body(source, "activate_stack")

    artifact_index = activate.index("ensure_static_frontend_artifact")
    browser_index = activate.index('"$BROWSER_COMMAND" start')
    playwright_index = activate.index("ensure_browser_playwright_ready")
    stack_index = activate.index("start_stack_detached")
    acceptance_index = activate.index("run_runtime_acceptance")
    assert artifact_index < browser_index < playwright_index < stack_index < acceptance_index


def test_android_browser_probe_uses_same_real_playwright_cdp_path_as_worker():
    source = WRAPPER.read_text(encoding="utf-8")
    probe = _function_body(source, "run_browser_playwright_probe")

    assert "probe_external_playwright_cdp" in probe
    assert "http://127.0.0.1:9222" in probe
    assert "playwright_attach_ready" in probe
    assert "browser_owned_by_jobtomatik" in probe

    runtime = (BACKEND_ROOT / "app/services/browser_runtime.py").read_text(encoding="utf-8")
    attachment_probe = runtime.split(
        "async def probe_external_playwright_cdp_attachment", 1
    )[1].split("\n\nasync def ", 1)[0]
    assert "_connect_external_playwright_over_cdp" in attachment_probe
    assert "_select_context_page" not in attachment_probe


def test_ordinary_restart_preserves_browser_and_fails_closed_when_playwright_is_stale():
    source = WRAPPER.read_text(encoding="utf-8")
    recovery = _function_body(source, "ensure_browser_playwright_ready")
    restart_case = source.split("  restart)\n", 1)[1].split("    ;;", 1)[0]

    assert '"$BROWSER_COMMAND" restart' not in source
    assert '"$BROWSER_COMMAND" recover' not in restart_case
    assert 'local recovery_mode="${1:-preserve}"' in recovery
    assert 'if [[ "$recovery_mode" != "recover_once" ]]; then' in recovery
    assert "ANDROID_BROWSER_PLAYWRIGHT_CDP_STALE action=preserve_browser_fail" in recovery
    assert recovery.count('"$BROWSER_COMMAND" recover') == 1


def test_launcher_installation_arms_one_use_deployment_recovery_marker():
    source = INSTALLER.read_text(encoding="utf-8")

    assert ".jobtomatik-deployment-restart.pending" in source
    assert 'touch "$DEPLOYMENT_RESTART_MARKER"' in source
    assert source.index('install_atomically "$STACK_SOURCE" "$STACK_DEST"') < source.index(
        'touch "$DEPLOYMENT_RESTART_MARKER"'
    )


def test_restart_consumes_deployment_marker_before_allowing_single_recovery():
    source = WRAPPER.read_text(encoding="utf-8")
    consume = _function_body(source, "consume_deployment_browser_recovery_mode")
    restart_case = source.split("  restart)\n", 1)[1].split("    ;;", 1)[0]

    assert '[[ -f "$DEPLOYMENT_RESTART_MARKER" ]]' in consume
    assert 'rm -f "$DEPLOYMENT_RESTART_MARKER"' in consume
    assert 'printf \'%s\\n\' "recover_once"' in consume
    assert 'printf \'%s\\n\' "preserve"' in consume
    assert 'browser_recovery_mode="$(consume_deployment_browser_recovery_mode)"' in restart_case
    assert 'activate_stack restart "$browser_recovery_mode"' in restart_case


def test_native_browser_recovery_waits_only_on_verified_supervisor_identity():
    source = BROWSER.read_text(encoding="utf-8")
    shutdown = _function_body(source, "wait_for_shutdown")
    stop_case = source.split("  stop)\n", 1)[1].split("    ;;", 1)[0]
    recovery_case = source.split("  restart|recover)\n", 1)[1].split("    ;;", 1)[0]

    assert "kill -0" in shutdown
    assert "supervisor_identity_matches" in shutdown
    assert "managed_browser_pids" in shutdown
    assert "! is_healthy" in shutdown
    assert 'wait_for_shutdown "$supervisor_pid"' in stop_case
    assert "ANDROID_BROWSER_CDP_STOP_ESCALATING signal=KILL" in stop_case
    assert "ANDROID_BROWSER_CDP_STOP_TIMEOUT" in stop_case
    assert '"$SCRIPT_PATH" stop' in recovery_case
    assert 'exec "$SCRIPT_PATH" start "$START_URL"' in recovery_case



    def test_browser_ownership_uses_exact_profile_and_port_not_executable_basename():
    source = BROWSER.read_text(encoding="utf-8")
    identity = _function_body(source, "browser_identity_matches")
    discovery = _function_body(source, "managed_browser_pids")
    stop_processes = _function_body(source, "stop_browser_processes")

    assert '"--remote-debugging-port=$CDP_PORT"' in identity
    assert '"--user-data-dir=$PROFILE_DIR"' in identity
    assert 'pgrep -f "remote-debugging-port=${CDP_PORT}"' in discovery
    assert "chromium-browser.*remote-debugging-port" not in source
    assert "signal_browser_if_managed" in stop_processes


def test_supervisor_records_exact_browser_pid_and_waits_for_that_process():
    source = BROWSER.read_text(encoding="utf-8")
    supervise_case = source.split("  supervise)\n", 1)[1].split("    ;;", 1)[0]

    assert 'browser_command >> "$BROWSER_LOG" 2>&1 &' in supervise_case
    assert "browser_pid=$!" in supervise_case
    assert 'echo "$browser_pid" > "$BROWSER_PID_FILE"' in supervise_case
    assert 'wait "$browser_pid"' in supervise_case
    assert 'rm -f "$BROWSER_PID_FILE"' in supervise_case


def test_stop_terminates_owned_browser_even_when_executable_name_is_not_chromium_browser(
    tmp_path,
):
    runtime_dir = tmp_path / "runtime"
    profile = tmp_path / "profile"
    runtime_dir.mkdir()
    profile.mkdir()
    port = 59321
    browser = _spawn_fake_owned_browser(profile=profile, port=port)
    try:
        time.sleep(0.1)
        assert _alive(browser)
        (runtime_dir / "chromium-browser.pid").write_text(str(browser.pid), encoding="utf-8")
        completed = subprocess.run(
            ["bash", str(BROWSER), "stop"],
            check=True,
            env=_browser_env(runtime_dir=runtime_dir, profile=profile, port=port),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert "ANDROID_BROWSER_CDP_STOPPED" in completed.stdout
        browser.wait(timeout=3)
        assert not _alive(browser)
    finally:
        _terminate(browser)


def test_stop_discovers_and_terminates_legacy_owned_browser_without_pid_file(tmp_path):
    runtime_dir = tmp_path / "runtime"
    profile = tmp_path / "profile"
    runtime_dir.mkdir()
    profile.mkdir()
    port = 59322
    browser = _spawn_fake_owned_browser(profile=profile, port=port)
    try:
        time.sleep(0.1)
        assert _alive(browser)
        completed = subprocess.run(
            ["bash", str(BROWSER), "stop"],
            check=True,
            env=_browser_env(runtime_dir=runtime_dir, profile=profile, port=port),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert "ANDROID_BROWSER_CDP_STOPPED" in completed.stdout
        browser.wait(timeout=3)
        assert not _alive(browser)
    finally:
        _terminate(browser)


def test_stop_rejects_reused_browser_pid_and_does_not_signal_innocent_process(tmp_path):
    runtime_dir = tmp_path / "runtime"
    profile = tmp_path / "profile"
    runtime_dir.mkdir()
    profile.mkdir()
    port = 59323
    innocent = subprocess.Popen(["sleep", "30"])
    try:
        (runtime_dir / "chromium-browser.pid").write_text(
            str(innocent.pid), encoding="utf-8"
        )
        completed = subprocess.run(
            ["bash", str(BROWSER), "stop"],
            check=True,
            env=_browser_env(runtime_dir=runtime_dir, profile=profile, port=port),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert "ANDROID_BROWSER_CDP_STOPPED" in completed.stdout
        assert _alive(innocent)
    finally:
        _terminate(innocent)


def test_already_running_start_never_enters_browser_recovery_path():
    source = WRAPPER.read_text(encoding="utf-8")
    start_case = source.split("  start)\n", 1)[1].split("    ;;", 1)[0]

    assert "supervisor_alive" in start_case
    assert "run_stack_foreground status" in start_case
    assert "run_frontend_guard status" in start_case
    assert "run_runtime_acceptance" in start_case
    live_branch = start_case.split("else", 1)[0]
    assert "consume_deployment_browser_recovery_mode" not in live_branch
    assert '"$BROWSER_COMMAND" recover' not in live_branch
