from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = BACKEND_ROOT / "scripts"


def _alive(process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> bool:
    return process.poll() is None


def _terminate(process: subprocess.Popen[bytes] | subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def test_identity_helper_refuses_to_signal_unrelated_live_process():
    innocent = subprocess.Popen(["sleep", "30"])
    try:
        command = f'''
set -euo pipefail
source "{SCRIPTS / 'jobtomatik_process_identity.sh'}"
set +e
jobtomatik_signal_if_identity TERM {innocent.pid} definitely-not-jobtomatik
rc=$?
set -e
[[ "$rc" -eq 3 ]]
kill -0 {innocent.pid}
'''
        subprocess.run(["bash", "-lc", command], check=True)
        assert _alive(innocent)
    finally:
        _terminate(innocent)


def test_runtime_pid_sanitizer_removes_reused_pid_without_signaling_process(tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    innocent = subprocess.Popen(["sleep", "30"])
    try:
        (runtime_dir / "api.pid").write_text(str(innocent.pid), encoding="utf-8")
        env = os.environ.copy()
        env["JOBTOMATIK_RUNTIME_DIR"] = str(runtime_dir)
        completed = subprocess.run(
            ["bash", str(SCRIPTS / "sanitize_android_runtime_pid_files.sh")],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "role=api" in completed.stdout
        assert "process_not_signaled" in completed.stdout
        assert not (runtime_dir / "api.pid").exists()
        assert _alive(innocent)
    finally:
        _terminate(innocent)


def test_runtime_pid_sanitizer_keeps_verified_managed_api_pid(tmp_path):
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()
    expected_argv0 = f"{BACKEND_ROOT / '.venv/bin/uvicorn'} app.main:app --port 8010"
    managed = subprocess.Popen(
        ["bash", "-lc", f'exec -a "{expected_argv0}" sleep 30'],
    )
    try:
        time.sleep(0.05)
        (runtime_dir / "api.pid").write_text(str(managed.pid), encoding="utf-8")
        env = os.environ.copy()
        env["JOBTOMATIK_RUNTIME_DIR"] = str(runtime_dir)
        completed = subprocess.run(
            ["bash", str(SCRIPTS / "sanitize_android_runtime_pid_files.sh")],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "ANDROID_MANAGED_PID_VERIFIED role=api" in completed.stdout
        assert (runtime_dir / "api.pid").read_text(encoding="utf-8") == str(managed.pid)
        assert _alive(managed)
    finally:
        _terminate(managed)


def test_native_browser_stop_does_not_signal_reused_supervisor_pid(tmp_path):
    runtime_dir = tmp_path / "native-runtime"
    profile_dir = tmp_path / "profile"
    runtime_dir.mkdir()
    profile_dir.mkdir()
    innocent = subprocess.Popen(["sleep", "30"])
    try:
        (runtime_dir / "chromium-supervisor.pid").write_text(
            str(innocent.pid), encoding="utf-8"
        )
        env = os.environ.copy()
        env.update(
            {
                "JOBTOMATIK_ANDROID_RUNTIME_DIR": str(runtime_dir),
                "JOBTOMATIK_ANDROID_BROWSER_PROFILE": str(profile_dir),
                "JOBTOMATIK_ANDROID_BROWSER_BIN": "/bin/true",
                "JOBTOMATIK_ANDROID_BROWSER_PORT": "59222",
            }
        )
        completed = subprocess.run(
            ["bash", str(SCRIPTS / "start_android_browser_cdp.sh"), "stop"],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "ANDROID_BROWSER_CDP_STOPPED" in completed.stdout
        assert "STALE_SUPERVISOR_PID_REJECTED" in completed.stderr
        assert _alive(innocent)
    finally:
        _terminate(innocent)


def test_native_stack_stop_does_not_signal_reused_proot_supervisor_pid(tmp_path):
    runtime_dir = tmp_path / "native-runtime"
    runtime_dir.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    proot_stub = fake_bin / "proot-distro"
    proot_stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    proot_stub.chmod(0o755)

    innocent = subprocess.Popen(["sleep", "30"])
    try:
        (runtime_dir / "proot-stack.pid").write_text(str(innocent.pid), encoding="utf-8")
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_bin}:{env.get('PATH', '')}",
                "JOBTOMATIK_ANDROID_RUNTIME_DIR": str(runtime_dir),
                "JOBTOMATIK_BROWSER_COMMAND": "/bin/true",
            }
        )
        completed = subprocess.run(
            ["bash", str(SCRIPTS / "jobtomatik_termux_wrapper.sh"), "stop"],
            check=True,
            env=env,
            capture_output=True,
            text=True,
        )
        assert "STALE_PROOT_PID_REJECTED" in completed.stderr
        assert _alive(innocent)
    finally:
        _terminate(innocent)


def test_installer_deploys_process_identity_helper(tmp_path):
    prefix = tmp_path / "termux-prefix"
    destination = prefix / "bin"
    destination.mkdir(parents=True)
    env = os.environ.copy()
    env["JOBTOMATIK_TERMUX_PREFIX"] = str(prefix)

    subprocess.run(
        ["bash", str(SCRIPTS / "install_android_native_browser_launcher.sh")],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )

    helper = destination / "jobtomatik_process_identity.sh"
    assert helper.is_file()
    assert os.access(helper, os.X_OK)
    assert "jobtomatik_signal_if_identity" in helper.read_text(encoding="utf-8")
