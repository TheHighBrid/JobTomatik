import os
import subprocess
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
INSTALLER = SCRIPTS / "install_android_native_browser_launcher.sh"


def test_installer_never_bakes_proot_home_into_native_termux_wrapper():
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "ADB_SERIAL_STATE" not in installer
    assert "JOBTOMATIK_ADB_SERIAL_STATE" not in installer
    assert ".jobtomatik-runtime/android-serial" not in installer
    assert "/root/.jobtomatik-runtime" not in installer
    assert 'python3 - "$STACK_DEST" <<\'PY\'' in installer
    assert 'adb connect "$serial"' in installer


def test_installed_wrapper_does_not_capture_installer_home(tmp_path):
    prefix = tmp_path / "termux-prefix"
    (prefix / "bin").mkdir(parents=True)
    proot_home = tmp_path / "proot-root"
    proot_home.mkdir()

    env = os.environ.copy()
    env["HOME"] = str(proot_home)
    env["JOBTOMATIK_TERMUX_PREFIX"] = str(prefix)
    result = subprocess.run(
        ["bash", str(INSTALLER)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    installed = (prefix / "bin" / "jobtomatik").read_text(encoding="utf-8")
    assert str(proot_home) not in installed
    assert "JOBTOMATIK_ADB_SERIAL_STATE" not in installed
    assert "ANDROID_NATIVE_CHROME_DEVICE_RECONNECTED" in installed


def test_native_runtime_state_is_resolved_by_native_termux_wrapper():
    wrapper = (SCRIPTS / "jobtomatik_termux_wrapper.sh").read_text(encoding="utf-8")

    assert (
        'RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"'
        in wrapper
    )
    assert "${JOBTOMATIK_ADB_SERIAL_STATE" not in wrapper
    assert "/root/.jobtomatik-runtime" not in wrapper
