from pathlib import Path


WRAPPER = Path(__file__).resolve().parents[1] / "scripts/jobtomatik_termux_wrapper.sh"


def test_existing_native_forward_is_never_rebound_without_ownership_validation():
    source = WRAPPER.read_text()
    function = "ensure_application_browser_endpoint() {" + source.split(
        "ensure_application_browser_endpoint() {", 1
    )[1].split("\n}\n", 1)[0]

    # Recovery must remain constrained to the selected device and native Chrome
    # socket. A transient discovery miss may be retried in Python, but the wrapper
    # must never silently take over an arbitrary listener or substitute Chromium.
    assert "ANDROID_NATIVE_CHROME_FORWARD_DEVICE_MISMATCH" in function
    assert "localabstract:chrome_devtools_remote" in function
    assert "--no-rebind" in function
    assert "chromium" not in function.lower()
