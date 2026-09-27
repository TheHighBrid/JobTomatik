from pathlib import Path


def test_android_installer_persists_and_restores_wireless_adb_serial():
    script = Path(__file__).parents[1] / "scripts" / "install_android_native_browser_launcher.sh"
    text = script.read_text(encoding="utf-8")
    assert "ADB_SERIAL_STATE" in text
    assert "ANDROID_NATIVE_CHROME_DEVICE_RESTORED" in text
    assert 'adb connect "$serial"' in text
    assert "ANDROID_NATIVE_CHROME_DEVICE_RECONNECTED" in text
    assert "chmod 600" in text


def test_persisted_serial_is_restricted_to_tcp_wireless_endpoint():
    script = Path(__file__).parents[1] / "scripts" / "install_android_native_browser_launcher.sh"
    text = script.read_text(encoding="utf-8")
    assert '[[ "$serial" =~ ^[^:[:space:]]+:[0-9]+$ ]]' in text
    assert '[[ -n "${ANDROID_SERIAL:-}" && "$ANDROID_SERIAL" =~ ^[^:[:space:]]+:[0-9]+$ ]]' in text
