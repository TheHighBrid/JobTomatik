from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "scripts" / "retire_stale_android_api.py"
SANITIZER = BACKEND_ROOT / "scripts" / "sanitize_android_runtime_pid_files.sh"
SPEC = importlib.util.spec_from_file_location("retire_stale_android_api", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _good_identity() -> dict:
    revision = "a" * 40
    return {
        "version": "phase12-runtime-identity-v1",
        "revision": revision,
        "expected_revision": revision,
        "role": "api",
        "known": True,
        "identity_sha256": "b" * 64,
        "submission_authorized": False,
        "outreach_authorized": False,
    }


def _emergency_argv(backend: Path) -> list[str]:
    return [
        str(backend / ".venv/bin/python"),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8010",
    ]


def test_emergency_python_module_uvicorn_shape_is_narrowly_recognized(tmp_path):
    backend = tmp_path / "backend"
    assert MODULE._is_jobtomatik_api_argv(_emergency_argv(backend), backend, 8010) is True

    unrelated = [
        "/usr/bin/python3",
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8010",
    ]
    assert MODULE._is_jobtomatik_api_argv(unrelated, backend, 8010) is False


def test_listener_pid_is_resolved_from_proc_socket_inode(tmp_path):
    proc = tmp_path / "proc"
    (proc / "net").mkdir(parents=True)
    (proc / "321/fd").mkdir(parents=True)
    (proc / "321/fd/7").symlink_to("socket:[424242]")
    (proc / "321/cmdline").write_bytes(b"python\0-m\0uvicorn\0")
    (proc / "net/tcp").write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n"
        "   0: 0100007F:1F4A 00000000:0000 0A 00000000:00000000 00:00000000 "
        "00000000 1000 0 424242 1 0000000000000000\n",
        encoding="utf-8",
    )
    assert MODULE._listener_pids(proc, 8010) == {321}


def test_runtime_identity_must_be_nonconsequential_jobtomatik_api():
    assert MODULE._identity_is_jobtomatik_api(_good_identity()) is True
    bad = _good_identity()
    bad["submission_authorized"] = True
    assert MODULE._identity_is_jobtomatik_api(bad) is False


def test_proc_net_restricted_fallback_retires_one_verified_owned_api(monkeypatch, tmp_path):
    backend = tmp_path / "backend"
    signaled = []

    monkeypatch.setattr(MODULE, "_candidate_api_pids", lambda *_: {777})
    monkeypatch.setattr(MODULE, "_listener_pids", lambda *_: set())
    monkeypatch.setattr(MODULE, "_read_environ", lambda *_: {})
    monkeypatch.setattr(MODULE, "_fetch_runtime_identity", lambda *_: _good_identity())
    monkeypatch.setattr(MODULE, "_port_accepting", lambda *_: False)
    monkeypatch.setattr(MODULE.os, "kill", lambda pid, sig: signaled.append((pid, sig)))

    assert MODULE.retire_stale_api(proc_root=tmp_path / "proc", backend_root=backend, port=8010) == 0
    assert signaled == [(777, signal.SIGTERM)]


def test_released_port_counts_as_retired_even_if_process_state_lingers(monkeypatch, tmp_path):
    backend = tmp_path / "backend"
    signaled = []
    accepting = iter((True, False))

    monkeypatch.setattr(MODULE, "_candidate_api_pids", lambda *_: {777})
    monkeypatch.setattr(MODULE, "_listener_pids", lambda *_: set())
    monkeypatch.setattr(MODULE, "_read_environ", lambda *_: {})
    monkeypatch.setattr(MODULE, "_fetch_runtime_identity", lambda *_: _good_identity())
    monkeypatch.setattr(MODULE, "_port_accepting", lambda *_: next(accepting))
    monkeypatch.setattr(MODULE.time, "sleep", lambda *_: None)
    monkeypatch.setattr(MODULE.os, "kill", lambda pid, sig: signaled.append((pid, sig)))

    assert MODULE.retire_stale_api(proc_root=tmp_path / "proc", backend_root=backend, port=8010) == 0
    assert signaled == [(777, signal.SIGTERM)]


def test_socket_owner_path_retires_only_intersection(monkeypatch, tmp_path):
    backend = tmp_path / "backend"
    identity = _good_identity()
    monkeypatch.setattr(MODULE, "_candidate_api_pids", lambda *_: {777, 888})
    monkeypatch.setattr(MODULE, "_listener_pids", lambda *_: {777})
    monkeypatch.setattr(MODULE, "_read_environ", lambda *_: {})

    pid, source = MODULE._select_verified_pid(
        proc_root=tmp_path / "proc",
        backend_root=backend,
        port=8010,
        identity=identity,
    )
    assert pid == 777
    assert source == "socket_owner"


def test_unknown_or_ambiguous_owned_processes_are_never_signaled(monkeypatch, tmp_path):
    backend = tmp_path / "backend"
    signaled = []
    monkeypatch.setattr(MODULE, "_candidate_api_pids", lambda *_: {777, 888})
    monkeypatch.setattr(MODULE, "_listener_pids", lambda *_: set())
    monkeypatch.setattr(MODULE, "_fetch_runtime_identity", lambda *_: _good_identity())
    monkeypatch.setattr(MODULE.os, "kill", lambda pid, sig: signaled.append((pid, sig)))

    assert MODULE.retire_stale_api(proc_root=tmp_path / "proc", backend_root=backend, port=8010) == 2
    assert signaled == []


def test_sanitizer_skips_optional_retirement_without_backend_venv(tmp_path):
    runtime_dir = tmp_path / "runtime"
    fake_venv = tmp_path / "missing-venv"
    runtime_dir.mkdir()
    env = os.environ.copy()
    env["JOBTOMATIK_RUNTIME_DIR"] = str(runtime_dir)
    env["JOBTOMATIK_BACKEND_VENV"] = str(fake_venv)

    completed = subprocess.run(
        ["bash", str(SANITIZER)],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    assert "ANDROID_STALE_API_RETIRE_SKIPPED reason=retirer_unavailable" in completed.stdout
    assert "ANDROID_RUNTIME_PID_FILES_SANITIZED" in completed.stdout


def test_sanitizer_runs_verified_retirement_only_after_api_pid_sanitization():
    sanitizer = SANITIZER.read_text(encoding="utf-8")
    api_sanitize = sanitizer.index('sanitize_pid_file api "$RUNTIME_DIR/api.pid"')
    assert '[[ -f "$RUNTIME_DIR/api.pid" ]] && return 0' in sanitizer
    assert "retire_stale_android_api.py" in sanitizer
    assert 'PROC_ROOT="${JOBTOMATIK_PROC_ROOT:-/proc}"' in sanitizer
    assert '--proc-root "$PROC_ROOT"' in sanitizer
    assert api_sanitize < sanitizer.rindex("retire_verified_stale_api_without_pid_file")
