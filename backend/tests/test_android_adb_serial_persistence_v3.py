from pathlib import Path


def test_reconnect_is_constrained_to_host_port_serial():
    text = (Path(__file__).parents[1] / "scripts" / "install_android_native_browser_launcher.sh").read_text()
    assert '[[ "$serial_connected" -ne 1 && "$serial" =~ ^[^:[:space:]]+:[0-9]+$ ]]' in text
    assert 'adb connect "$serial"' in text
