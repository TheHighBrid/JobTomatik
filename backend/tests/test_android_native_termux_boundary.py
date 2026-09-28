from __future__ import annotations

import os
from pathlib import Path
import subprocess


BACKEND_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = BACKEND_ROOT / "scripts/install_android_native_browser_launcher.sh"


def test_launcher_installed_from_proot_persists_adb_state_in_native_termux_home(tmp_path):
    termux_files = tmp_path / "data" / "data" / "com.termux" / "files"
    termux_prefix = termux_files / "usr"
    (termux_prefix / "bin").mkdir(parents=True)

    proot_home = tmp_path / "proot-root"
    proot_home.mkdir()

    serial = "10.0.0.231:45697"
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(proot_home),
            "JOBTOMATIK_TERMUX_PREFIX": str(termux_prefix),
            "ANDROID_SERIAL": serial,
        }
    )

    subprocess.run(
        ["bash", str(INSTALLER)],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )

    native_state = termux_files / "home" / ".jobtomatik-runtime" / "android-serial"
    leaked_proot_state = proot_home / ".jobtomatik-runtime" / "android-serial"
    installed_wrapper = termux_prefix / "bin" / "jobtomatik"

    assert native_state.read_text(encoding="utf-8").strip() == serial
    assert not leaked_proot_state.exists()

    wrapper_text = installed_wrapper.read_text(encoding="utf-8")
    assert str(native_state) in wrapper_text
    assert str(proot_home) not in wrapper_text
    assert "/root/.jobtomatik-runtime/android-serial" not in wrapper_text
