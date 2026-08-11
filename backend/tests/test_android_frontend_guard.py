from __future__ import annotations

import json
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
MANAGER = BACKEND_ROOT / "scripts/manage_android_stack.sh"
STATIC_SERVER = BACKEND_ROOT / "scripts/serve_static_frontend.py"


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


def _guard_env(
    tmp_path: Path,
    *,
    frontend_root: Path,
    proc_root: Path,
    port: int,
    revision: str = "a" * 40,
    artifact_root: Path | None = None,
) -> dict[str, str]:
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "JOBTOMATIK_FRONTEND_ROOT": str(frontend_root),
            "JOBTOMATIK_RUNTIME_DIR": str(runtime_dir),
            "JOBTOMATIK_PROC_ROOT": str(proc_root),
            "JOBTOMATIK_FRONTEND_URL": f"http://127.0.0.1:{port}",
            "JOBTOMATIK_RUNTIME_REVISION": revision,
            "JOBTOMATIK_BACKEND_VENV": str(Path(sys.executable).resolve().parent.parent),
        }
    )
    if artifact_root is not None:
        env["JOBTOMATIK_FRONTEND_ARTIFACT_ROOT"] = str(artifact_root)
    return env


def _fake_vite_proc_entry(proc_root: Path, pid: int, frontend_root: Path) -> None:
    entry = proc_root / str(pid)
    entry.mkdir(parents=True)
    (entry / "cmdline").write_bytes(
        b"node\x00node_modules/.bin/vite\x00--host\x000.0.0.0\x00--port\x003000\x00"
    )
    (entry / "cwd").symlink_to(frontend_root)


def _fake_static_proc_entry(
    proc_root: Path,
    pid: int,
    *,
    python_path: Path,
    artifact_root: Path,
    revision: str,
) -> None:
    entry = proc_root / str(pid)
    entry.mkdir(parents=True)
    cmdline = [
        str(python_path),
        str(STATIC_SERVER),
        "--root",
        str(artifact_root / "dist"),
        "--manifest",
        str(artifact_root / "jobtomatik-frontend-manifest.json"),
        "--revision",
        revision,
        "--host",
        "127.0.0.1",
        "--port",
        "3000",
    ]
    (entry / "cmdline").write_bytes(b"\0".join(part.encode("utf-8") for part in cmdline) + b"\0")


def _static_artifact(tmp_path: Path, revision: str) -> tuple[Path, Path, Path]:
    artifact_root = tmp_path / "artifact"
    dist = artifact_root / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><div id="root"></div>', encoding="utf-8")
    manifest = artifact_root / "jobtomatik-frontend-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "artifact_type": "jobtomatik-static-frontend",
                "revision": revision,
                "dist_tree_sha256": "dist-test-sha",
                "package_lock_sha256": "lock-test-sha",
                "build_api_url": "http://127.0.0.1:8010",
            }
        ),
        encoding="utf-8",
    )
    return artifact_root, dist, manifest


def test_frontend_guard_has_valid_bash_syntax_and_no_broad_kill():
    subprocess.run(["bash", "-n", str(GUARD)], check=True)
    content = GUARD.read_text(encoding="utf-8")
    assert "pkill" not in content
    assert "killall" not in content
    assert "jobtomatik_process_identity.sh" in content
    assert "jobtomatik_pid_has_all_tokens" in content
    assert "serve_static_frontend.py" in content
    assert "legacy_vite_pid_matches" in content
    assert '"--port"' in content
    assert '"3000"' in content


def test_wrapper_requires_frontend_guard_for_adoption_and_status():
    wrapper = WRAPPER.read_text(encoding="utf-8")
    assert "run_frontend_guard()" in wrapper
    assert "run_stack_foreground status && run_frontend_guard status" in wrapper
    assert "run_frontend_guard reset" in wrapper
    assert "run_frontend_guard status" in wrapper
    assert "run_runtime_acceptance" in wrapper


def test_manager_enforces_static_frontend_ownership_on_first_upgrade_path():
    manager = MANAGER.read_text(encoding="utf-8")
    assert 'FRONTEND_GUARD="$BACKEND_ROOT/scripts/android_frontend_guard.sh"' in manager
    assert "frontend_managed_ready()" in manager
    assert "frontend_artifact_ready()" in manager
    assert 'frontend_guard reset' in manager
    assert 'FRONTEND: EXISTING_STATIC_ATTESTED' in manager
    assert 'FRONTEND: READY_BUT_UNMANAGED_OR_STALE' in manager
    assert 'FRONTEND: STARTED_STATIC_ATTESTED' in manager
    assert '&& "$frontend_managed" -eq 1' in manager
    assert "npm run dev" not in manager

    start_stack = manager.split("start_stack() {", 1)[1].split("\n}\n\nrestart_stack", 1)[0]
    assert start_stack.index("status_stack") < start_stack.index('echo "JOBTOMATIK_ANDROID_STACK_READY"')


def test_guard_retires_narrowly_identified_legacy_jobtomatik_vite(tmp_path):
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
        _fake_vite_proc_entry(proc_root, process.pid, frontend_root)
        result = subprocess.run(
            ["bash", str(GUARD), "reset"],
            env=_guard_env(tmp_path, frontend_root=frontend_root, proc_root=proc_root, port=port),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert "ANDROID_FRONTEND_EXISTING_JOBTOMATIK_RETIRED" in result.stdout
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


def test_guard_status_requires_exact_static_process_and_artifact_identity(tmp_path):
    frontend_root = tmp_path / "frontend"
    frontend_root.mkdir()
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    port = _free_port()
    revision = "b" * 40
    artifact_root, dist, manifest = _static_artifact(tmp_path, revision)
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(exist_ok=True)
    python_path = Path(sys.executable).resolve()

    process = subprocess.Popen(
        [
            str(python_path),
            str(STATIC_SERVER),
            "--root",
            str(dist),
            "--manifest",
            str(manifest),
            "--revision",
            revision,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}")
        _fake_static_proc_entry(
            proc_root,
            process.pid,
            python_path=python_path,
            artifact_root=artifact_root,
            revision=revision,
        )
        (runtime_dir / "frontend.pid").write_text(str(process.pid), encoding="utf-8")
        result = subprocess.run(
            ["bash", str(GUARD), "status"],
            env=_guard_env(
                tmp_path,
                frontend_root=frontend_root,
                proc_root=proc_root,
                port=port,
                revision=revision,
                artifact_root=artifact_root,
            ),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr + result.stdout
        assert f"ANDROID_FRONTEND_STATIC_MANAGED_READY pid={process.pid}" in result.stdout
    finally:
        process.terminate()
        process.wait(timeout=5)
