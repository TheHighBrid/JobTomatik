"""Non-authorizing proof for one ephemeral supervised Lever runtime launch.

The marker is deliberately bound to the exact native ``jobtomatik-pilot`` process
that created it. A stale file cannot arm a later restart after that process exits or
its PID is recycled. The marker never grants per-application submission approval.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MARKER_PATH = BACKEND_ROOT / ".runtime" / "lever-supervised-pilot-runtime.json"
MARKER_SCHEMA_VERSION = 1
MARKER_MODE = "lever_supervised_ephemeral"
OWNER_CMDLINE_TOKEN = "jobtomatik_pilot_wrapper.sh"


def _process_start_ticks(pid: int) -> int | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # /proc/<pid>/stat encloses comm in parentheses. Split only after the final ')'
    # so a process name containing whitespace cannot shift the field positions.
    end = raw.rfind(")")
    if end < 0:
        return None
    fields_after_comm = raw[end + 2 :].split()
    # Field 3 (state) is index 0 here, so field 22 (starttime) is index 19.
    if len(fields_after_comm) <= 19:
        return None
    try:
        return int(fields_after_comm[19])
    except ValueError:
        return None


def _process_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", errors="replace")


def load_marker(path: Path = DEFAULT_MARKER_PATH) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def lever_supervised_runtime_marker_active(
    path: Path = DEFAULT_MARKER_PATH,
) -> bool:
    marker = load_marker(path)
    if marker is None:
        return False
    if marker.get("schema_version") != MARKER_SCHEMA_VERSION:
        return False
    if marker.get("mode") != MARKER_MODE:
        return False
    if marker.get("submission_approval_granted") is not False:
        return False

    try:
        owner_pid = int(marker.get("owner_pid"))
        owner_start_ticks = int(marker.get("owner_start_ticks"))
    except (TypeError, ValueError):
        return False
    if owner_pid <= 0 or owner_start_ticks <= 0:
        return False
    if _process_start_ticks(owner_pid) != owner_start_ticks:
        return False
    if OWNER_CMDLINE_TOKEN not in _process_cmdline(owner_pid):
        return False
    return True


__all__ = [
    "DEFAULT_MARKER_PATH",
    "MARKER_MODE",
    "MARKER_SCHEMA_VERSION",
    "OWNER_CMDLINE_TOKEN",
    "lever_supervised_runtime_marker_active",
    "load_marker",
]
