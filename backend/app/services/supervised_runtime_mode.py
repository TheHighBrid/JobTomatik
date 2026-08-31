"""Non-authorizing proof for one ephemeral supervised Lever runtime launch.

The marker is deliberately bound to the exact native ``jobtomatik-pilot`` process
that created it, one cryptographically random restart token, and one repository
revision. A stale file, recycled PID, unrelated process, or later restart cannot reuse
it. The marker never grants per-application submission approval.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MARKER_PATH = BACKEND_ROOT / ".runtime" / "lever-supervised-pilot-runtime.json"
MARKER_SCHEMA_VERSION = 2
MARKER_MODE = "lever_supervised_ephemeral"
OWNER_CMDLINE_TOKENS = (
    "jobtomatik-pilot",
    "jobtomatik_pilot_wrapper.sh",
)
REVISION_RE = re.compile(r"^[0-9a-f]{7,64}$")
MIN_LAUNCH_TOKEN_LENGTH = 32


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


def _owner_cmdline_token(pid: int) -> str | None:
    cmdline = _process_cmdline(pid)
    return next((token for token in OWNER_CMDLINE_TOKENS if token in cmdline), None)


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _normalized_revision(value: str) -> str:
    revision = str(value or "").strip().lower()
    if not REVISION_RE.fullmatch(revision):
        raise RuntimeError("LEVER_PILOT_MARKER_INVALID_RUNTIME_REVISION")
    return revision


def _launch_token_digest(value: str) -> str:
    token = str(value or "")
    if len(token) < MIN_LAUNCH_TOKEN_LENGTH:
        raise RuntimeError("LEVER_PILOT_MARKER_LAUNCH_TOKEN_TOO_SHORT")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_marker(path: Path = DEFAULT_MARKER_PATH) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def lever_supervised_runtime_marker_active(
    path: Path = DEFAULT_MARKER_PATH,
    *,
    expected_launch_token: str | None = None,
    expected_revision: str | None = None,
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

    marker_token = str(marker.get("owner_cmdline_token") or "")
    if marker_token not in OWNER_CMDLINE_TOKENS:
        return False
    if marker_token not in _process_cmdline(owner_pid):
        return False

    marker_revision = str(marker.get("runtime_revision") or "").strip().lower()
    if not REVISION_RE.fullmatch(marker_revision):
        return False
    marker_launch_digest = str(marker.get("launch_token_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", marker_launch_digest):
        return False

    if expected_revision is not None:
        try:
            normalized_expected_revision = _normalized_revision(expected_revision)
        except RuntimeError:
            return False
        if marker_revision != normalized_expected_revision:
            return False

    if expected_launch_token is not None:
        try:
            expected_digest = _launch_token_digest(expected_launch_token)
        except RuntimeError:
            return False
        if not hmac.compare_digest(marker_launch_digest, expected_digest):
            return False
    return True


def create_owner_bound_marker(
    owner_pid: int,
    *,
    launch_token: str,
    runtime_revision: str,
    path: Path = DEFAULT_MARKER_PATH,
) -> dict[str, Any]:
    """Create a capability marker bound to one owner, restart token, and revision."""

    owner_pid = int(owner_pid)
    if owner_pid <= 0:
        raise RuntimeError("LEVER_PILOT_MARKER_INVALID_OWNER_PID")
    owner_start_ticks = _process_start_ticks(owner_pid)
    owner_cmdline_token = _owner_cmdline_token(owner_pid)
    if owner_start_ticks is None or owner_start_ticks <= 0:
        raise RuntimeError("LEVER_PILOT_MARKER_OWNER_PROCESS_UNAVAILABLE")
    if owner_cmdline_token is None:
        raise RuntimeError("LEVER_PILOT_MARKER_OWNER_IDENTITY_MISMATCH")

    normalized_revision = _normalized_revision(runtime_revision)
    launch_token_sha256 = _launch_token_digest(launch_token)
    marker = {
        "schema_version": MARKER_SCHEMA_VERSION,
        "mode": MARKER_MODE,
        "submission_approval_granted": False,
        "owner_pid": owner_pid,
        "owner_start_ticks": owner_start_ticks,
        "owner_cmdline_token": owner_cmdline_token,
        "runtime_revision": normalized_revision,
        "launch_token_sha256": launch_token_sha256,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(marker, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()

    if not lever_supervised_runtime_marker_active(
        path,
        expected_launch_token=launch_token,
        expected_revision=normalized_revision,
    ):
        clear_owner_bound_marker(path)
        raise RuntimeError("LEVER_PILOT_MARKER_ACTIVE_VERIFICATION_FAILED")
    return marker


def clear_owner_bound_marker(path: Path = DEFAULT_MARKER_PATH) -> None:
    """Remove the ephemeral capability marker before any ordinary safe restart."""

    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


__all__ = [
    "DEFAULT_MARKER_PATH",
    "MARKER_MODE",
    "MARKER_SCHEMA_VERSION",
    "MIN_LAUNCH_TOKEN_LENGTH",
    "OWNER_CMDLINE_TOKENS",
    "clear_owner_bound_marker",
    "create_owner_bound_marker",
    "lever_supervised_runtime_marker_active",
    "load_marker",
]
