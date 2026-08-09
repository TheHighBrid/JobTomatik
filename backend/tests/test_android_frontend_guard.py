from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


BACKEND_ROOT = Path(__file__).resolve().parents[1]
GUARD = BACKEND_ROOT / "scripts/android_frontend_guard.sh"
WRAPPER = BACKEND_ROOT / "scripts/jobtomatik_termux_wrapper.sh"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=0.5) as response:  # noqa: S310 - loopback test server
                if int(getattr(response, "status", 200)) == 200:
                    return
        except Exception:
            time.sleep(0.05)
    raise AssertionError(f"test server did not become ready: {url}")


def _guard_env(tmp_path: Path, *, frontend_root: Path, proc_root: Path, port: int) -> dict[str, str]:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "JOBTOMATIK_FRONTEND_ROOT": str(frontend_root),
            "JOBTOMATIK_RUNTIME_DIR": str(runtime_dir),
            "JOBTOMATIK_PROC_ROOT": str(proc_root),
            "JOBTOMATIK_FRONTEND_URL": f"http://127.0.0.1:{port}",
        }
    )
    return env


def _fake_proc_entry(proc_root: Path, pid: int, frontend_root: Path) -> None:
    entry = proc_root / str(pid)
    entry.mkdir(parents=True)
    (entry / "cmdline").write_bytes(b"node\0node_modules/.bin/vite\0--host\00.0.0.0\0--port\03000\0")
    (entry / "cwd").symlink_to(frontend_root)


def test_frontend_guard_has_valid_bash_syntax_and_no_broad_kill():
    subprocess.run(["bash", "-n", str(GUARD)], check=True)
    content = GUARD.read_text(encoding="utf-8")
    assert "pkill" not in content
    assert "killall" not in content
    assert 'readlink "$proc/cwd"' in content
    assert '"$cwd" == "$FRONTEND_ROOT"' in content
    assert '"$cmdline" == *"vite"*' in content
    assert '"--port 3000"' in content


def test_wrapper_requires_frontend_guard_for_adoption_and_status():
    wrapper = WRAPPER.read_text(encoding="utf-8")
    assert "run_frontend_guard()" in wrapper
    assert "run_stack_foreground status && run_frontend_guard status" in wrapper
    assert "run_frontend_guard reset" in wrapper
    assert "run_frontend_guard status" in wrapper


def test_guard_retires_narrowly_identified_jobtomatik_vite(tmp_path):
    frontend_root = tmp_path / "frontend"
    frontend_root.mkdir()
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    port = _free_port()

    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=frontend_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}")
        _fake_proc_entry(proc_root, process.pid, frontend_root)
        result = subprocess.run(
            ["bash", str(GUARD), "reset"],
            env=_guard_env(tmp_path, frontend_root=frontend_root, proc_root=proc_root, port=port),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert "ANDROID_FRONTEND_EXISTING_VITE_RETIRED" in result.stdout
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_guard_refuses_to_kill_unrelated_service_on_frontend_port(tmp_path):
    frontend_root = tmp_path / "frontend"
    frontend_root.mkdir()
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    port = _free_port()

    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}")
        result = subprocess.run(
            ["bash", str(GUARD), "reset"],
            env=_guard_env(tmp_path, frontend_root=frontend_root, proc_root=proc_root, port=port),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0
        assert "ANDROID_FRONTEND_UNMANAGED_PORT_3000" in result.stderr
        assert process.poll() is None
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_guard_status_requires_pid_file_and_reachable_frontend(tmp_path):
    frontend_root = tmp_path / "frontend"
    frontend_root.mkdir()
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    port = _free_port()
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir()

    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=frontend_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}")
        (runtime_dir / "frontend.pid").write_text(str(process.pid), encoding="utf-8")
        result = subprocess.run(
            ["bash", str(GUARD), "status"],
            env=_guard_env(tmp_path, frontend_root=frontend_root, proc_root=proc_root, port=port),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert f"ANDROID_FRONTEND_MANAGED_READY pid={process.pid}" in result.stdout
    finally:
        process.terminate()
        process.wait(timeout=5)
