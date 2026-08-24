from pathlib import Path


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


def test_android_wrapper_proves_real_playwright_before_proot_stack_start():
    source = WRAPPER.read_text(encoding="utf-8")
    activate = _function_body(source, "activate_stack")

    artifact_index = activate.index("ensure_static_frontend_artifact")
    browser_index = activate.index('"$BROWSER_COMMAND" start')
    playwright_index = activate.index("ensure_browser_playwright_ready")
    stack_index = activate.index("start_stack_detached")
    acceptance_index = activate.index("run_runtime_acceptance")
    assert artifact_index < browser_index < playwright_index < stack_index < acceptance_index


def test_android_browser_recovery_probe_checks_attachment_without_selecting_pages():
    source = WRAPPER.read_text(encoding="utf-8")
    probe = _function_body(source, "run_browser_playwright_probe")

    assert "probe_external_playwright_cdp_attachment" in probe
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
    assert "! is_healthy" in shutdown
    assert 'wait_for_shutdown "$supervisor_pid"' in stop_case
    assert 'supervisor_pid=""' in stop_case
    assert "ANDROID_BROWSER_CDP_STOP_TIMEOUT" in stop_case
    assert '"$SCRIPT_PATH" stop' in recovery_case
    assert 'exec "$SCRIPT_PATH" start "$START_URL"' in recovery_case


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
