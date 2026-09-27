from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"


def test_installer_never_bakes_proot_home_into_native_termux_wrapper():
    installer = (SCRIPTS / "install_android_native_browser_launcher.sh").read_text(
        encoding="utf-8"
    )

    assert "ADB_SERIAL_STATE" not in installer
    assert "JOBTOMATIK_ADB_SERIAL_STATE" not in installer
    assert "$HOME/.jobtomatik-runtime/android-serial" not in installer
    assert 'python3 - "$STACK_DEST"' not in installer
    assert 'install_atomically "$STACK_SOURCE" "$STACK_DEST"' in installer


def test_native_runtime_state_is_resolved_by_native_termux_wrapper():
    wrapper = (SCRIPTS / "jobtomatik_termux_wrapper.sh").read_text(encoding="utf-8")

    assert (
        'RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"'
        in wrapper
    )
    assert "${JOBTOMATIK_ADB_SERIAL_STATE" not in wrapper
    assert "/root/.jobtomatik-runtime" not in wrapper
