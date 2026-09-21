"""Execute real shell functions with all device/process effects stubbed."""
import os
from pathlib import Path
import subprocess
import tempfile

import pytest


WRAPPER = Path(__file__).resolve().parents[1] / "scripts/jobtomatik_termux_wrapper.sh"


def function(name):
    source = WRAPPER.read_text()
    return name + "() {" + source.split(name + "() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"


def run(code):
    env = os.environ.copy()
    env.pop("ANDROID_SERIAL", None)
    env.pop("JOBTOMATIK_ANDROID_APPLICATION_BROWSER_MODE", None)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".sh",
        delete=False,
    ) as handle:
        handle.write("set -euo pipefail\n")
        handle.write(code)
        script_path = Path(handle.name)
    try:
        return subprocess.run(
            ["bash", str(script_path)],
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    finally:
        script_path.unlink(missing_ok=True)


def test_failed_attach_never_calls_browser_recovery():
    result = run(function("ensure_browser_playwright_ready") + """
BROWSER_COMMAND=browser_stub
browser_stub() { echo FORBIDDEN_BROWSER_ACTION; }
run_browser_playwright_probe() { return 1; }
ensure_browser_playwright_ready
""")
    assert result.returncode != 0
    assert "preserve_browser_fail" in result.stderr
    assert "FORBIDDEN_BROWSER_ACTION" not in result.stdout


def test_disconnect_after_endpoint_check_cannot_start_stack_or_chromium():
    result = run(function("activate_stack") + function("ensure_browser_playwright_ready") + """
sanitize_runtime_pid_files() { :; }
ensure_static_frontend_artifact() { :; }
ensure_application_browser_endpoint() { echo INITIAL_NATIVE_CHECK_PASSED; }
run_stack_foreground() { :; }
run_browser_playwright_probe() { return 1; }
BROWSER_COMMAND=browser_stub
browser_stub() { echo FORBIDDEN_BROWSER_ACTION; }
start_stack_detached() { echo FORBIDDEN_STACK_START; }
run_runtime_acceptance() { :; }
ensure_pilot_controller() { :; }
activate_stack restart
""")
    assert result.returncode != 0
    assert "INITIAL_NATIVE_CHECK_PASSED" in result.stdout
    assert "FORBIDDEN" not in result.stdout


def test_warm_start_rejects_wrong_native_identity():
    source = WRAPPER.read_text()
    start = source.split('\ncase "$ACTION" in\n', 1)[1].split("  start)\n", 1)[1].split("    ;;", 1)[0]
    result = run("""
verify_backend_environment() { :; }
supervisor_alive() { return 0; }
run_stack_foreground() { return 0; }
run_frontend_guard() { return 0; }
ensure_application_browser_endpoint() { echo NATIVE_IDENTITY_REJECTED; return 1; }
run_runtime_acceptance() { echo FORBIDDEN_ACCEPTANCE; }
ensure_pilot_controller() { :; }
""" + start)
    assert result.returncode != 0
    assert "NATIVE_IDENTITY_REJECTED" in result.stdout
    assert "FORBIDDEN_ACCEPTANCE" not in result.stdout


@pytest.mark.parametrize("devices", ["", "first\\tdevice\\nsecond\\tdevice"])
def test_disconnected_or_ambiguous_devices_do_not_forward(devices):
    result = run(function("ensure_application_browser_endpoint") + f"""
run_application_browser_contract() {{ printf 'native_chrome\\nhttp://127.0.0.1:9223\\n9223\\n'; }}
native_android_chrome_cdp_ready() {{ return 1; }}
adb() {{ if [[ "$1" == devices ]]; then printf 'List of devices attached\\n{devices}\\n'; else echo FORBIDDEN_FORWARD; fi; }}
ensure_application_browser_endpoint
""")
    assert result.returncode != 0
    assert "DEVICE_REQUIRED" in result.stderr
    assert "FORBIDDEN_FORWARD" not in result.stdout


def test_forward_error_is_not_hidden_or_rebound():
    result = run(function("ensure_application_browser_endpoint") + """
run_application_browser_contract() { printf 'native_chrome\\nhttp://127.0.0.1:9333\\n9333\\n'; }
native_android_chrome_cdp_ready() { return 1; }
adb() { if [[ "$1" == devices ]]; then printf 'List of devices attached\\nselected\\tdevice\\n'; else echo "ADB_ARGS:$*"; return 1; fi; }
ensure_application_browser_endpoint
""")
    assert result.returncode != 0
    assert "-s selected forward --no-rebind tcp:9333 localabstract:chrome_devtools_remote" in result.stdout
    assert "FORWARD_FAILED" in result.stderr




def test_isolated_browser_profile_requirement_fails_before_identity_or_forward():
    result = run(function("ensure_application_browser_endpoint") + """
JOBTOMATIK_REQUIRE_ISOLATED_BROWSER_PROFILE=1
run_application_browser_contract() { printf 'native_chrome\nhttp://127.0.0.1:9223\n9223\n'; }
native_android_chrome_cdp_ready() { echo FORBIDDEN_IDENTITY_PROBE; return 0; }
adb() { echo FORBIDDEN_ADB; }
ensure_application_browser_endpoint
""")
    assert result.returncode != 0
    assert "PROFILE_ISOLATION_UNSUPPORTED" in result.stderr
    assert "FORBIDDEN" not in result.stdout


def test_ready_endpoint_requires_exact_selected_adb_forward_binding():
    result = run(function("ensure_application_browser_endpoint") + """
run_application_browser_contract() { printf 'native_chrome\\nhttp://127.0.0.1:9223\\n9223\\n'; }
native_android_chrome_cdp_ready() { echo IDENTITY_READY; return 0; }
adb() {
  if [[ "$1" == devices ]]; then
    printf 'List of devices attached\\nselected\\tdevice\\n'
  elif [[ "$1" == forward && "$2" == --list ]]; then
    printf 'selected tcp:9223 localabstract:chrome_devtools_remote\\n'
  else
    echo FORBIDDEN_FORWARD
    return 1
  fi
}
ensure_application_browser_endpoint
""")
    assert result.returncode == 0
    assert "IDENTITY_READY" in result.stdout
    assert "FORBIDDEN_FORWARD" not in result.stdout


def test_ready_endpoint_rejects_forward_owned_by_another_device():
    result = run(function("ensure_application_browser_endpoint") + """
ANDROID_SERIAL=selected
run_application_browser_contract() { printf 'native_chrome\\nhttp://127.0.0.1:9223\\n9223\\n'; }
native_android_chrome_cdp_ready() { echo FORBIDDEN_IDENTITY_ACCEPT; return 0; }
adb() {
  if [[ "$1" == devices ]]; then
    printf 'List of devices attached\\nselected\\tdevice\\nother\\tdevice\\n'
  elif [[ "$1" == forward && "$2" == --list ]]; then
    printf 'other tcp:9223 localabstract:chrome_devtools_remote\\n'
  else
    echo FORBIDDEN_FORWARD
    return 1
  fi
}
ensure_application_browser_endpoint
""")
    assert result.returncode != 0
    assert "FORWARD_DEVICE_MISMATCH" in result.stderr
    assert "FORBIDDEN_IDENTITY_ACCEPT" not in result.stdout
    assert "FORBIDDEN_FORWARD" not in result.stdout


def test_ready_endpoint_without_matching_adb_forward_fails_closed():
    result = run(function("ensure_application_browser_endpoint") + """
run_application_browser_contract() { printf 'native_chrome\\nhttp://127.0.0.1:9223\\n9223\\n'; }
native_android_chrome_cdp_ready() { echo IDENTITY_READY; return 0; }
adb() {
  if [[ "$1" == devices ]]; then
    printf 'List of devices attached\\nselected\\tdevice\\n'
  elif [[ "$1" == forward && "$2" == --list ]]; then
    return 0
  else
    echo FORBIDDEN_FORWARD
    return 1
  fi
}
ensure_application_browser_endpoint
""")
    assert result.returncode != 0
    assert "FORWARD_UNVERIFIED" in result.stderr
    assert "IDENTITY_READY" in result.stdout
    assert "FORBIDDEN_FORWARD" not in result.stdout


def test_browser_preflight_persists_contract_before_playwright_probe():
    source = WRAPPER.read_text()
    preflight = source.split('\ncase "$ACTION" in\n', 1)[1].split("  browser-preflight)\n", 1)[1].split("    ;;", 1)[0]
    result = run("""
verify_backend_environment() { echo VERIFY; }
ensure_application_browser_endpoint() { echo ENDPOINT; }
run_stack_foreground() { echo "STACK:$1"; }
ensure_browser_playwright_ready() { echo "PROBE"; }
""" + preflight)
    assert result.returncode == 0
    output = result.stdout
    assert output.index("ENDPOINT") < output.index("STACK:configure-browser") < output.index("PROBE")


def test_absent_deployment_restart_marker_is_successful_noop(tmp_path):
    marker = tmp_path / "missing-restart-marker"
    result = run(
        function("consume_deployment_restart_marker")
        + f"""
DEPLOYMENT_RESTART_MARKER="{marker}"
consume_deployment_restart_marker
"""
    )
    assert result.returncode == 0
    assert not marker.exists()


def test_native_stop_preserves_browser_even_when_disconnected():
    source = WRAPPER.read_text()
    stop = source.split('\ncase "$ACTION" in\n', 1)[1].split("  stop)\n", 1)[1].split("    ;;", 1)[0]
    result = run("""
stop_pilot_controller() { :; }
stop_stack_supervisor() { :; }
BROWSER_COMMAND=browser_stub
browser_stub() { echo FORBIDDEN_BROWSER_STOP; }
""" + stop)
    assert result.returncode == 0
    assert "PRESERVED_ON_STOP" in result.stdout
    assert "FORBIDDEN_BROWSER_STOP" not in result.stdout


def test_missing_native_chrome_is_started_then_verified():
    result = run(
        function("request_native_android_chrome_foreground")
        + function("ensure_application_browser_endpoint")
        + """
probe_count=0
run_application_browser_contract() { printf 'native_chrome\\nhttp://127.0.0.1:9223\\n9223\\n'; }
native_android_chrome_cdp_ready() {
  probe_count=$((probe_count + 1))
  [[ "$probe_count" -ge 3 ]]
}
sleep() { :; }
adb() {
  if [[ "$1" == devices ]]; then
    printf 'List of devices attached\\nselected\\tdevice\\n'
  elif [[ "$1" == forward && "$2" == --list ]]; then
    printf 'selected tcp:9223 localabstract:chrome_devtools_remote\\n'
  elif [[ "$1" == -s && "$2" == selected && "$3" == shell && "$4" == monkey ]]; then
    printf 'CHROME_LAUNCH\\n'
  else
    echo "UNEXPECTED_ADB:$*" >&2
    return 1
  fi
}
ensure_application_browser_endpoint
"""
    )
    assert result.returncode == 0
    assert "ANDROID_NATIVE_CHROME_LAUNCH_REQUESTED" in result.stdout
    assert "ANDROID_NATIVE_CHROME_CDP_READY" in result.stdout
    assert "CHROME_LAUNCH" not in result.stdout


def test_new_forward_bootstraps_native_chrome_without_browser_substitution():
    result = run(
        function("request_native_android_chrome_foreground")
        + function("ensure_application_browser_endpoint")
        + """
probe_count=0
run_application_browser_contract() { printf 'native_chrome\\nhttp://127.0.0.1:9223\\n9223\\n'; }
native_android_chrome_cdp_ready() {
  probe_count=$((probe_count + 1))
  [[ "$probe_count" -ge 3 ]]
}
sleep() { :; }
adb() {
  if [[ "$1" == devices ]]; then
    printf 'List of devices attached\\nselected\\tdevice\\n'
  elif [[ "$1" == forward && "$2" == --list ]]; then
    return 0
  elif [[ "$1" == -s && "$2" == selected && "$3" == forward ]]; then
    return 0
  elif [[ "$1" == -s && "$2" == selected && "$3" == shell && "$4" == monkey ]]; then
    return 0
  else
    echo "UNEXPECTED_ADB:$*" >&2
    return 1
  fi
}
ensure_application_browser_endpoint
"""
    )
    assert result.returncode == 0
    assert "ANDROID_NATIVE_CHROME_LAUNCH_REQUESTED" in result.stdout
    assert "ANDROID_NATIVE_CHROME_CDP_READY" in result.stdout


def test_native_chrome_launch_failure_stays_fail_closed():
    result = run(
        function("request_native_android_chrome_foreground")
        + function("ensure_application_browser_endpoint")
        + """
run_application_browser_contract() { printf 'native_chrome\\nhttp://127.0.0.1:9223\\n9223\\n'; }
native_android_chrome_cdp_ready() { return 1; }
adb() {
  if [[ "$1" == devices ]]; then
    printf 'List of devices attached\\nselected\\tdevice\\n'
  elif [[ "$1" == forward && "$2" == --list ]]; then
    printf 'selected tcp:9223 localabstract:chrome_devtools_remote\\n'
  elif [[ "$1" == -s && "$2" == selected && "$3" == shell && "$4" == monkey ]]; then
    return 1
  else
    echo "UNEXPECTED_ADB:$*" >&2
    return 1
  fi
}
ensure_application_browser_endpoint
"""
    )
    assert result.returncode != 0
    assert "ANDROID_NATIVE_CHROME_LAUNCH_FAILED" in result.stderr
    assert "Chromium" not in result.stdout


def test_native_chrome_bootstrap_never_force_stops_user_browser():
    source = WRAPPER.read_text()
    helper = function("request_native_android_chrome_foreground")
    assert "force-stop" not in helper
    assert "pm clear" not in helper
    assert "com.android.chrome" in helper
    assert "android.intent.category.LAUNCHER" in helper
