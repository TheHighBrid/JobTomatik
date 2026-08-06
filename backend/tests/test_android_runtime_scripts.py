import os
from pathlib import Path
import subprocess

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/start_android_browser_cdp.sh",
        "scripts/jobtomatik_termux_wrapper.sh",
        "scripts/install_android_native_browser_launcher.sh",
        "scripts/manage_android_stack.sh",
    ],
)
def test_android_runtime_shell_script_has_valid_bash_syntax(relative_path):
    script = BACKEND_ROOT / relative_path
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_android_launcher_installer_copies_native_commands(tmp_path):
    prefix = tmp_path / "termux-prefix"
    destination = prefix / "bin"
    destination.mkdir(parents=True)

    environment = os.environ.copy()
    environment["JOBTOMATIK_TERMUX_PREFIX"] = str(prefix)

    subprocess.run(
        ["bash", str(BACKEND_ROOT / "scripts/install_android_native_browser_launcher.sh")],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    browser_command = destination / "jobtomatik-browser"
    stack_command = destination / "jobtomatik"
    assert browser_command.is_file()
    assert stack_command.is_file()
    assert os.access(browser_command, os.X_OK)
    assert os.access(stack_command, os.X_OK)
    assert "remote-debugging-port" in browser_command.read_text(encoding="utf-8")
    assert "proot-distro login" in stack_command.read_text(encoding="utf-8")


def test_termux_wrapper_does_not_assume_a_proot_storage_layout():
    wrapper = (BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh").read_text(
        encoding="utf-8"
    )

    assert "installed-rootfs" not in wrapper
    assert "containers/" not in wrapper
    assert "install_android_native_browser_launcher.sh" in wrapper
    assert "proot-distro login" in wrapper
