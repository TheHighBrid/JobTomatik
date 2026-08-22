from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh"
BROWSER = BACKEND_ROOT / "scripts/start_android_browser_cdp.sh"


def _function_body(source: str, name: str) -> str:
    marker = f"{name}() {{"
    start = source.index(marker)
    tail = source[start + len(marker) :]
    end = tail.index("\n}\n")
    return tail[:end]


def test_android_wrapper_proves_real_playwright_before_proot_stack_start():
    source = WRAPPER.read_text(encoding="utf-8")
    activate = _function_body(source, "activate_stack")

    assert '"$BROWSER_COMMAND" start' in activate
    assert "ensure_browser_playwright_ready" in activate
    assert "start_stack_detached" in activate
    assert activate.index('"$BROWSER_COMMAND" start') < activate.index(
        "ensure_browser_playwright_ready"
    ) < activate.index("start_stack_detached")


def test_android_browser_probe_uses_same_real_playwright_cdp_path_as_worker():
    source = WRAPPER.read_text(encoding="utf-8")
    probe = _function_body(source, "run_browser_playwright_probe")

    assert "probe_external_playwright_cdp" in probe
    assert "http://127.0.0.1:9222" in probe
    assert "playwright_attach_ready" in probe
    assert "browser_owned_by_jobtomatik" in probe


def test_stale_http_cdp_recovery_recycles_native_browser_at_most_once():
    source = WRAPPER.read_text(encoding="utf-8")
    recovery = _function_body(source, "ensure_browser_playwright_ready")

    assert recovery.count('"$BROWSER_COMMAND" recover') == 1
    assert '"$BROWSER_COMMAND" restart' not in source
    assert "ANDROID_BROWSER_PLAYWRIGHT_CDP_STALE action=recover_once" in recovery
    assert "ANDROID_BROWSER_PLAYWRIGHT_CDP_RECOVERED" in recovery
    assert "ANDROID_BROWSER_PLAYWRIGHT_CDP_RECOVERY_FAILED" in recovery
    assert recovery.count("run_browser_playwright_probe") == 2


def test_native_browser_recovery_waits_for_old_process_and_cdp_endpoint_to_stop():
    source = BROWSER.read_text(encoding="utf-8")
    shutdown = _function_body(source, "wait_for_shutdown")
    stop_case = source.split("  stop)\n", 1)[1].split("    ;;", 1)[0]
    recovery_case = source.split("  restart|recover)\n", 1)[1].split("    ;;", 1)[0]

    assert "kill -0" in shutdown
    assert "! is_healthy" in shutdown
    assert 'wait_for_shutdown "$supervisor_pid"' in stop_case
    assert "ANDROID_BROWSER_CDP_STOP_TIMEOUT" in stop_case
    assert '"$SCRIPT_PATH" stop' in recovery_case
    assert 'exec "$SCRIPT_PATH" start "$START_URL"' in recovery_case


def test_already_running_start_checks_stack_before_any_browser_recovery():
    source = WRAPPER.read_text(encoding="utf-8")
    activate = _function_body(source, "activate_stack")

    live_check = 'if [[ "$action" == "start" ]] && supervisor_alive; then'
    assert live_check in activate
    assert activate.index(live_check) < activate.index('"$BROWSER_COMMAND" start')
    ready_branch = activate.split(live_check, 1)[1].split("  fi", 1)[0]
    assert "run_stack_foreground status" in ready_branch
    assert "run_frontend_guard status" in ready_branch
    assert "run_runtime_acceptance" in ready_branch
    assert '"$BROWSER_COMMAND" recover' not in ready_branch


def test_browser_recovery_happens_before_new_stack_acceptance_not_in_status_path():
    source = WRAPPER.read_text(encoding="utf-8")
    activate = _function_body(source, "activate_stack")
    status_case = source.split("  status)\n", 1)[1].split("    ;;", 1)[0]

    assert activate.index("ensure_browser_playwright_ready") < activate.rindex(
        "run_runtime_acceptance"
    )
    assert "ensure_browser_playwright_ready" not in status_case
