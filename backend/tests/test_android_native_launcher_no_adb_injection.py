from pathlib import Path


def _installer_text() -> str:
    return (
        Path(__file__).parents[1]
        / "scripts"
        / "install_android_native_browser_launcher.sh"
    ).read_text(encoding="utf-8")


def test_native_installer_does_not_inject_adb_state_or_reconnect_code():
    text = _installer_text()
    forbidden = (
        "ADB_SERIAL_STATE",
        "ANDROID_NATIVE_CHROME_DEVICE_RESTORED",
        "ANDROID_NATIVE_CHROME_DEVICE_RECONNECTED",
        'adb connect "$serial"',
        "ANDROID_LAUNCHER_SERIAL_STATE_PATCH_TARGET_MISSING",
        "ANDROID_LAUNCHER_ADB_RECONNECT_PATCH_TARGET_MISSING",
    )
    for token in forbidden:
        assert token not in text


def test_native_installer_copies_stack_wrapper_without_rewriting_it():
    text = _installer_text()
    assert 'install_atomically "$STACK_SOURCE" "$STACK_DEST"' in text
    assert 'python3 - "$STACK_DEST"' not in text
    assert "path.write_text" not in text


def test_native_installer_keeps_deployment_marker_contract():
    text = _installer_text()
    assert 'touch "$DEPLOYMENT_RESTART_MARKER"' in text
    assert 'echo "ANDROID_BROWSER_LAUNCHER_INSTALLED"' in text
