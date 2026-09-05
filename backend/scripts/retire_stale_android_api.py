#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import time
import urllib.request
from pathlib import Path

REVISION_RE = re.compile(r"^[0-9a-f]{7,64}$", re.IGNORECASE)
IDENTITY_VERSION = "phase12-runtime-identity-v1"
LISTEN_STATE = "0A"


def _listener_inodes(proc_root: Path, port: int) -> set[str]:
    inodes: set[str] = set()
    for relative in ("net/tcp", "net/tcp6"):
        table = proc_root / relative
        try:
            lines = table.read_text(encoding="utf-8", errors="replace").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10:
                continue
            try:
                local_port = int(parts[1].rsplit(":", 1)[1], 16)
            except (IndexError, ValueError):
                continue
            if local_port == port and parts[3] == LISTEN_STATE:
                inodes.add(parts[9])
    return inodes


def _listener_pids(proc_root: Path, port: int) -> set[int]:
    inodes = _listener_inodes(proc_root, port)
    if not inodes:
        return set()
    pids: set[int] = set()
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return set()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        fd_dir = entry / "fd"
        try:
            fds = list(fd_dir.iterdir())
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target.startswith("socket:[") and target[8:-1] in inodes:
                pids.add(int(entry.name))
                break
    return pids


def _read_argv(proc_root: Path, pid: int) -> list[str]:
    try:
        raw = (proc_root / str(pid) / "cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]


def _flag_value(argv: list[str], flag: str) -> str | None:
    positions = [index for index, value in enumerate(argv) if value == flag]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        return None
    return argv[positions[0] + 1]


def _is_jobtomatik_api_argv(argv: list[str], backend_root: Path, port: int) -> bool:
    if not argv or "app.main:app" not in argv:
        return False
    if _flag_value(argv, "--host") != "127.0.0.1":
        return False
    if _flag_value(argv, "--port") != str(port):
        return False

    venv_bin = str(backend_root / ".venv" / "bin")
    interpreter_owned = argv[0].startswith(f"{venv_bin}/")
    if not interpreter_owned:
        return False

    module_launch = any(
        argv[index] == "-m" and index + 1 < len(argv) and argv[index + 1] == "uvicorn"
        for index in range(len(argv))
    )
    console_launch = str(backend_root / ".venv" / "bin" / "uvicorn") in argv
    return module_launch or console_launch


def _fetch_runtime_identity(port: int) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/system/runtime-identity",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _identity_is_jobtomatik_api(payload: dict) -> bool:
    revision = str(payload.get("revision") or "")
    return bool(
        payload.get("version") == IDENTITY_VERSION
        and payload.get("role") == "api"
        and payload.get("known") is True
        and REVISION_RE.fullmatch(revision)
        and payload.get("identity_sha256")
        and payload.get("submission_authorized") is False
        and payload.get("outreach_authorized") is False
    )


def retire_stale_api(*, proc_root: Path, backend_root: Path, port: int) -> int:
    pids = _listener_pids(proc_root, port)
    if not pids:
        print(f"ANDROID_STALE_API_NONE port={port}")
        return 0
    if len(pids) != 1:
        print(f"ANDROID_STALE_API_RETIRE_REFUSED reason=ambiguous_listener_pids pids={sorted(pids)}")
        return 2

    pid = next(iter(pids))
    argv = _read_argv(proc_root, pid)
    if not _is_jobtomatik_api_argv(argv, backend_root, port):
        print(f"ANDROID_STALE_API_RETIRE_REFUSED reason=unknown_process pid={pid}")
        return 2

    try:
        identity = _fetch_runtime_identity(port)
    except Exception as exc:
        print(f"ANDROID_STALE_API_RETIRE_REFUSED reason=identity_unavailable pid={pid} error={type(exc).__name__}")
        return 2
    if not _identity_is_jobtomatik_api(identity):
        print(f"ANDROID_STALE_API_RETIRE_REFUSED reason=identity_mismatch pid={pid}")
        return 2

    print(
        "ANDROID_STALE_API_VERIFIED "
        f"pid={pid} revision={identity.get('revision')} role=api action=terminate"
    )
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    for _ in range(40):
        if not _listener_pids(proc_root, port):
            print(f"ANDROID_STALE_API_RETIRED pid={pid} port={port}")
            return 0
        time.sleep(0.125)

    print(f"ANDROID_STALE_API_RETIRE_FAILED pid={pid} port={port}")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-root", type=Path, required=True)
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    return retire_stale_api(
        proc_root=args.proc_root,
        backend_root=args.backend_root,
        port=args.port,
    )


if __name__ == "__main__":
    raise SystemExit(main())
