from pathlib import Path


def test_fresh_shell_wireless_serial_state_contract():
    text = (Path(__file__).parents[1] / "scripts" / "install_android_native_browser_launcher.sh").read_text()
    required = ["ADB_SERIAL_STATE", "ANDROID_NATIVE_CHROME_DEVICE_RESTORED", "ANDROID_NATIVE_CHROME_DEVICE_RECONNECTED", 'adb connect "$serial"', "chmod 600"]
    assert all(token in text for token in required)
