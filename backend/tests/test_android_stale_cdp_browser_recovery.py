from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
WRAPPER = BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh"


def _function_body(source: str, name: str) -> str:
    marker = f"{name}() {{"
    start = source.index(marker)
    tail = source[start + len(marker) :]
    end = tail.index("\n}\n")
    return tail[:end]


def test_android_wrapper_proves_real_playwright_before_proot_stack_start():
    source = WRAPPER.read_text(encoding="utf-8")
    activate = _function_body(source, "activate_stack")

    assert "ensure_browser_playwright_ready" in activate
    assert "start_stack_detached" in activate
    assert activate.index("ensure_browser_playwright_ready") < activate.index(
        "start_stack_detached"
    )


def test_android_browser_probe_uses_same_real_playwright_cdp_path_as_worker():
    source = WRAPPER.read_text(encoding="utf-8")
    probe = _function_body(source, "run_browser_playwright_probe")

    assert "probe_external_playwright_cdp" in probe
    assert "http://127.0.0.1:9222" in probe
    assert "playwright_attach_ready" in probe
    assert "browser_owned_by_jobtomatik" in probe


def test_stale_http_cdp_recovery_restarts_native_browser_at_most_once():
    source = WRAPPER.read_text(encoding="utf-8")
    recovery = _function_body(source, "ensure_browser_playwright_ready")

    assert recovery.count('"$BROWSER_COMMAND" restart') == 1
    assert "ANDROID_BROWSER_PLAYWRIGHT_CDP_STALE action=restart_once" in recovery
    assert "ANDROID_BROWSER_PLAYWRIGHT_CDP_RECOVERED" in recovery
    assert "ANDROID_BROWSER_PLAYWRIGHT_CDP_RECOVERY_FAILED" in recovery
    assert recovery.count("run_browser_playwright_probe") == 2


def test_browser_recovery_happens_before_runtime_acceptance_not_in_status_path():
    source = WRAPPER.read_text(encoding="utf-8")
    activate = _function_body(source, "activate_stack")
    status_case = source.split("  status)\n", 1)[1].split("    ;;", 1)[0]

    assert activate.index("ensure_browser_playwright_ready") < activate.index(
        "run_runtime_acceptance"
    )
    assert "ensure_browser_playwright_ready" not in status_case
