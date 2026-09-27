import os
import subprocess
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"
INSTALLER = SCRIPTS / "install_android_native_browser_launcher.sh"


def test_installer_never_bakes_proot_home_into_native_termux_wrapper():
    installer = INSTALLER.read_text(encoding="utf-8")

    assert '$HOME/.jobtomatik-runtime/android-serial' not in installer
    assert "/root/.jobtomatik-runtime" not in installer
    assert 'python3 - "$STACK_DEST" <<\'PY\'' in installer
    assert 'local adb_serial_state="${JOBTOMATIK_ADB_SERIAL_STATE:-$RUNTIME_DIR/android-serial}"' in installer
    assert 'adb connect "$serial"' in installer


def test_installed_wrapper_uses_native_runtime_state_not_installer_home(tmp_path):
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
    assert "/root/.jobtomatik-runtime" not in installed
    assert 'JOBTOMATIK_ADB_SERIAL_STATE:-$RUNTIME_DIR/android-serial' in installed
    assert "ANDROID_NATIVE_CHROME_DEVICE_RESTORED" in installed
    assert "ANDROID_NATIVE_CHROME_DEVICE_RECONNECTED" in installed
    assert 'adb connect "$serial"' in installed


def test_persisted_target_precedes_generic_single_device_fallback(tmp_path):
    prefix = tmp_path / "termux-prefix"
    (prefix / "bin").mkdir(parents=True)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "proot-root")
    env["JOBTOMATIK_TERMUX_PREFIX"] = str(prefix)
    Path(env["HOME"]).mkdir()

    result = subprocess.run(
        ["bash", str(INSTALLER)], env=env, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr

    installed = (prefix / "bin" / "jobtomatik").read_text(encoding="utf-8")
    restored = installed.index("ANDROID_NATIVE_CHROME_DEVICE_RESTORED")
    autoselected = installed.index("ANDROID_NATIVE_CHROME_DEVICE_AUTOSELECTED")
    assert restored < autoselected


def test_installed_wrapper_persists_only_verified_wireless_endpoint(tmp_path):
    prefix = tmp_path / "termux-prefix"
    (prefix / "bin").mkdir(parents=True)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "proot-root")
    env["JOBTOMATIK_TERMUX_PREFIX"] = str(prefix)
    Path(env["HOME"]).mkdir()

    result = subprocess.run(
        ["bash", str(INSTALLER)], env=env, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr

    installed = (prefix / "bin" / "jobtomatik").read_text(encoding="utf-8")
    assert '[[ "$serial" =~ ^[^:[:space:]]+:[0-9]+$ ]]' in installed
    assert 'printf \'%s\\n\' "$serial" > "${adb_serial_state}.tmp.$$"' in installed
    assert 'chmod 600 "${adb_serial_state}.tmp.$$"' in installed
    assert 'mv -f "${adb_serial_state}.tmp.$$" "$adb_serial_state"' in installed


def test_source_wrapper_keeps_runtime_dir_native():
    wrapper = (SCRIPTS / "jobtomatik_termux_wrapper.sh").read_text(encoding="utf-8")

    assert (
        'RUNTIME_DIR="${JOBTOMATIK_ANDROID_RUNTIME_DIR:-$HOME/.jobtomatik-runtime}"'
        in wrapper
    )
    assert "/root/.jobtomatik-runtime" not in wrapper
