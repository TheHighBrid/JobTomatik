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


def _read_environ(proc_root: Path, pid: int) -> dict[str, str]:
    try:
        raw = (proc_root / str(pid) / "environ").read_bytes()
    except OSError:
        return {}
    result: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        result[key.decode("utf-8", errors="replace")] = value.decode(
            "utf-8", errors="replace"
        )
    return result


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
    if not argv[0].startswith(f"{venv_bin}/"):
        return False

    module_launch = any(
        argv[index] == "-m" and index + 1 < len(argv) and argv[index + 1] == "uvicorn"
        for index in range(len(argv))
    )
    console_launch = str(backend_root / ".venv" / "bin" / "uvicorn") in argv
    return module_launch or console_launch


def _candidate_api_pids(proc_root: Path, backend_root: Path, port: int) -> set[int]:
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return set()
    candidates: set[int] = set()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if _is_jobtomatik_api_argv(_read_argv(proc_root, pid), backend_root, port):
            candidates.add(pid)
    return candidates


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


def _environment_consistent_with_identity(
    proc_root: Path, pid: int, identity: dict
) -> bool:
    environment = _read_environ(proc_root, pid)
    if not environment:
        return True

    role = environment.get("JOBTOMATIK_RUNTIME_ROLE")
    revision = environment.get("JOBTOMATIK_RUNTIME_REVISION")
    expected = environment.get("JOBTOMATIK_EXPECTED_REVISION")
    if role is not None and role != "api":
        return False
    if revision is not None and revision.lower() != str(identity.get("revision") or "").lower():
        return False
    identity_expected = str(identity.get("expected_revision") or "")
    if expected is not None and identity_expected and expected.lower() != identity_expected.lower():
        return False
    return True


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _select_verified_pid(
    *, proc_root: Path, backend_root: Path, port: int, identity: dict
) -> tuple[int | None, str]:
    candidates = _candidate_api_pids(proc_root, backend_root, port)
    if not candidates:
        return None, "no_owned_api_candidate"

    socket_pids = _listener_pids(proc_root, port)
    if socket_pids:
        matched = candidates & socket_pids
        if len(matched) != 1:
            return None, f"ambiguous_socket_owner candidates={sorted(candidates)} listeners={sorted(socket_pids)}"
        pid = next(iter(matched))
        source = "socket_owner"
    else:
        # Android may deny access to /proc/net/tcp even for the same app UID. In that
        # case fall back only when there is exactly one exact JobTomatik API command.
        if len(candidates) != 1:
            return None, f"ambiguous_owned_candidates pids={sorted(candidates)}"
        pid = next(iter(candidates))
        source = "unique_owned_process_fallback"

    if not _environment_consistent_with_identity(proc_root, pid, identity):
        return None, f"process_identity_environment_mismatch pid={pid}"
    return pid, source


def retire_stale_api(*, proc_root: Path, backend_root: Path, port: int) -> int:
    candidates = _candidate_api_pids(proc_root, backend_root, port)
    try:
        identity = _fetch_runtime_identity(port)
    except Exception as exc:
        if not candidates:
            print(f"ANDROID_STALE_API_NONE port={port}")
            return 0
        print(
            "ANDROID_STALE_API_RETIRE_REFUSED "
            f"reason=identity_unavailable pids={sorted(candidates)} error={type(exc).__name__}"
        )
        return 2

    if not _identity_is_jobtomatik_api(identity):
        print("ANDROID_STALE_API_RETIRE_REFUSED reason=identity_mismatch")
        return 2

    pid, source = _select_verified_pid(
        proc_root=proc_root,
        backend_root=backend_root,
        port=port,
        identity=identity,
    )
    if pid is None:
        print(f"ANDROID_STALE_API_RETIRE_REFUSED reason={source}")
        return 2

    print(
        "ANDROID_STALE_API_VERIFIED "
        f"pid={pid} revision={identity.get('revision')} role=api source={source} action=terminate"
    )
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    for _ in range(40):
        if not _pid_alive(pid):
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
