"""Fail-closed runtime lease for the supervised Lever Android window.

The lease has two stages:

* ``pending`` is bound to the native ``jobtomatik-pilot`` owner, one random launch
  token, and one repository revision. It is never sufficient for submission.
* ``active`` is created only after the managed restart has completed successfully.
  It is bound to the exact attested API and worker PIDs/start times, the same revision,
  and a short expiry. If either process restarts, disappears, or changes identity, the
  lease becomes invalid immediately.

The marker never grants a per-application approval. Persisted consequential switches
remain OFF; callers must combine this lease with the existing exact one-time approval
and target checks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = BACKEND_ROOT / ".runtime"
DEFAULT_MARKER_PATH = RUNTIME_DIR / "lever-supervised-pilot-runtime.json"
RUNTIME_ACCEPTANCE_PATH = RUNTIME_DIR / "android-runtime-acceptance.json"
MARKER_SCHEMA_VERSION = 3
MARKER_MODE = "lever_supervised_ephemeral"
MARKER_STATE_PENDING = "pending"
MARKER_STATE_ACTIVE = "active"
OWNER_CMDLINE_TOKENS = (
    "jobtomatik-pilot",
    "jobtomatik_pilot_wrapper.sh",
)
MANAGED_RUNTIME_ROLES = frozenset({"api", "worker"})
RUNTIME_PID_FILES = {
    "api": RUNTIME_DIR / "api.pid",
    "worker": RUNTIME_DIR / "celery.pid",
}
RUNTIME_CMDLINE_TOKENS = {
    "api": ("uvicorn", "app.main:app"),
    "worker": ("celery", "app.celery_app", "worker"),
}
LAUNCH_TOKEN_ENV_KEY = "JOBTOMATIK_LEVER_PILOT_LAUNCH_TOKEN"
REVISION_RE = re.compile(r"^[0-9a-f]{7,64}$")
MIN_LAUNCH_TOKEN_LENGTH = 32
ACTIVE_LEASE_TTL_SECONDS = 60 * 60


def _process_start_ticks(pid: int) -> int | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    end = raw.rfind(")")
    if end < 0:
        return None
    fields_after_comm = raw[end + 2 :].split()
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


def _process_environ(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
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


def _pid_file_value(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def _atomic_write_marker(path: Path, marker: dict[str, Any]) -> None:
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


def load_marker(path: Path = DEFAULT_MARKER_PATH) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _common_marker_valid(marker: dict[str, Any] | None) -> bool:
    return bool(
        marker
        and marker.get("schema_version") == MARKER_SCHEMA_VERSION
        and marker.get("mode") == MARKER_MODE
        and marker.get("submission_approval_granted") is False
        and REVISION_RE.fullmatch(str(marker.get("runtime_revision") or "").lower())
    )


def pending_runtime_marker_active(
    path: Path = DEFAULT_MARKER_PATH,
    *,
    expected_launch_token: str | None = None,
    expected_revision: str | None = None,
) -> bool:
    marker = load_marker(path)
    if not _common_marker_valid(marker):
        return False
    assert marker is not None
    if marker.get("state") != MARKER_STATE_PENDING:
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

    marker_revision = str(marker.get("runtime_revision") or "").lower()
    if expected_revision is not None:
        try:
            if marker_revision != _normalized_revision(expected_revision):
                return False
        except RuntimeError:
            return False

    marker_launch_digest = str(marker.get("launch_token_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", marker_launch_digest):
        return False
    if expected_launch_token is not None:
        try:
            expected_digest = _launch_token_digest(expected_launch_token)
        except RuntimeError:
            return False
        if not hmac.compare_digest(marker_launch_digest, expected_digest):
            return False
    return True


def _managed_process_identity(
    role: str,
    pid: int,
    *,
    runtime_revision: str,
) -> dict[str, Any] | None:
    if role not in MANAGED_RUNTIME_ROLES or pid <= 0:
        return None
    start_ticks = _process_start_ticks(pid)
    if start_ticks is None or start_ticks <= 0:
        return None
    cmdline = _process_cmdline(pid)
    if not cmdline or not all(token in cmdline for token in RUNTIME_CMDLINE_TOKENS[role]):
        return None
    process_env = _process_environ(pid)
    if process_env.get("JOBTOMATIK_RUNTIME_ROLE") != role:
        return None
    if str(process_env.get("JOBTOMATIK_RUNTIME_REVISION") or "").lower() != runtime_revision:
        return None
    if str(process_env.get("JOBTOMATIK_EXPECTED_REVISION") or "").lower() != runtime_revision:
        return None
    return {
        "pid": pid,
        "start_ticks": start_ticks,
        "cmdline_sha256": hashlib.sha256(cmdline.encode("utf-8")).hexdigest(),
    }


def create_owner_bound_marker(
    owner_pid: int,
    *,
    launch_token: str,
    runtime_revision: str,
    path: Path = DEFAULT_MARKER_PATH,
) -> dict[str, Any]:
    """Create a pending marker. Pending state never authorizes submission."""

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
    marker = {
        "schema_version": MARKER_SCHEMA_VERSION,
        "mode": MARKER_MODE,
        "state": MARKER_STATE_PENDING,
        "submission_approval_granted": False,
        "owner_pid": owner_pid,
        "owner_start_ticks": owner_start_ticks,
        "owner_cmdline_token": owner_cmdline_token,
        "runtime_revision": normalized_revision,
        "launch_token_sha256": _launch_token_digest(launch_token),
        "created_at_epoch": int(time.time()),
    }
    _atomic_write_marker(path, marker)
    if not pending_runtime_marker_active(
        path,
        expected_launch_token=launch_token,
        expected_revision=normalized_revision,
    ):
        clear_owner_bound_marker(path)
        raise RuntimeError("LEVER_PILOT_MARKER_PENDING_VERIFICATION_FAILED")
    return marker


def activate_runtime_lease(
    *,
    launch_token: str,
    runtime_revision: str,
    path: Path = DEFAULT_MARKER_PATH,
    ttl_seconds: int = ACTIVE_LEASE_TTL_SECONDS,
) -> dict[str, Any]:
    """Promote one verified pending transition to a short-lived process-bound lease."""

    normalized_revision = _normalized_revision(runtime_revision)
    if not pending_runtime_marker_active(
        path,
        expected_launch_token=launch_token,
        expected_revision=normalized_revision,
    ):
        raise RuntimeError("LEVER_PILOT_RUNTIME_PENDING_MARKER_INACTIVE")
    pending = load_marker(path) or {}

    process_identities: dict[str, Any] = {}
    for role in sorted(MANAGED_RUNTIME_ROLES):
        pid = _pid_file_value(RUNTIME_PID_FILES[role])
        identity = _managed_process_identity(
            role,
            int(pid or 0),
            runtime_revision=normalized_revision,
        )
        if identity is None:
            raise RuntimeError(f"LEVER_PILOT_RUNTIME_{role.upper()}_IDENTITY_UNVERIFIED")
        process_identities[role] = identity

    now = int(time.time())
    bounded_ttl = max(60, min(int(ttl_seconds), ACTIVE_LEASE_TTL_SECONDS))
    marker = {
        "schema_version": MARKER_SCHEMA_VERSION,
        "mode": MARKER_MODE,
        "state": MARKER_STATE_ACTIVE,
        "submission_approval_granted": False,
        "runtime_revision": normalized_revision,
        "launch_token_sha256": pending.get("launch_token_sha256"),
        "transition_owner_pid": pending.get("owner_pid"),
        "activated_at_epoch": now,
        "expires_at_epoch": now + bounded_ttl,
        "processes": process_identities,
    }
    _atomic_write_marker(path, marker)

    # A shadow runtime-acceptance receipt created before lease activation no longer
    # describes the current operating state. Removing it makes every shadow admission
    # fail closed until an ordinary disarmed restart writes a new receipt.
    try:
        RUNTIME_ACCEPTANCE_PATH.unlink()
    except FileNotFoundError:
        pass

    status = runtime_lease_status(
        path,
        expected_launch_token=launch_token,
        expected_revision=normalized_revision,
    )
    if not status.get("active"):
        clear_owner_bound_marker(path)
        raise RuntimeError("LEVER_PILOT_RUNTIME_ACTIVE_VERIFICATION_FAILED")
    return marker


def runtime_lease_status(
    path: Path = DEFAULT_MARKER_PATH,
    *,
    expected_launch_token: str | None = None,
    expected_revision: str | None = None,
) -> dict[str, Any]:
    marker = load_marker(path)
    result = {
        "active": False,
        "state": marker.get("state") if isinstance(marker, dict) else None,
        "runtime_revision": marker.get("runtime_revision") if isinstance(marker, dict) else None,
        "expires_at_epoch": marker.get("expires_at_epoch") if isinstance(marker, dict) else None,
        "blockers": [],
    }
    blockers: list[str] = result["blockers"]
    if not _common_marker_valid(marker):
        blockers.append("marker_invalid")
        return result
    assert marker is not None
    if marker.get("state") != MARKER_STATE_ACTIVE:
        blockers.append("marker_not_active")
        return result

    marker_revision = str(marker.get("runtime_revision") or "").lower()
    if expected_revision is not None:
        try:
            if marker_revision != _normalized_revision(expected_revision):
                blockers.append("runtime_revision_mismatch")
        except RuntimeError:
            blockers.append("runtime_revision_invalid")

    if expected_launch_token is not None:
        try:
            expected_digest = _launch_token_digest(expected_launch_token)
        except RuntimeError:
            blockers.append("launch_token_invalid")
        else:
            if not hmac.compare_digest(
                str(marker.get("launch_token_sha256") or ""),
                expected_digest,
            ):
                blockers.append("launch_token_mismatch")

    try:
        expires_at = int(marker.get("expires_at_epoch"))
    except (TypeError, ValueError):
        expires_at = 0
    if expires_at <= int(time.time()):
        blockers.append("lease_expired")

    processes = marker.get("processes")
    if not isinstance(processes, dict):
        blockers.append("process_binding_missing")
        return result
    for role in sorted(MANAGED_RUNTIME_ROLES):
        recorded = processes.get(role)
        if not isinstance(recorded, dict):
            blockers.append(f"{role}_binding_missing")
            continue
        try:
            pid = int(recorded.get("pid"))
            start_ticks = int(recorded.get("start_ticks"))
        except (TypeError, ValueError):
            blockers.append(f"{role}_binding_invalid")
            continue
        current = _managed_process_identity(role, pid, runtime_revision=marker_revision)
        if current is None:
            blockers.append(f"{role}_process_unverified")
            continue
        if int(current.get("start_ticks") or 0) != start_ticks:
            blockers.append(f"{role}_process_restarted")
        if str(current.get("cmdline_sha256") or "") != str(recorded.get("cmdline_sha256") or ""):
            blockers.append(f"{role}_process_identity_changed")

    result["active"] = not blockers
    return result


def lever_supervised_runtime_lease_active(
    path: Path = DEFAULT_MARKER_PATH,
    *,
    required_role: str | None = None,
) -> bool:
    """Return true only for the exact bound managed API/worker process."""

    role = str(required_role or os.environ.get("JOBTOMATIK_RUNTIME_ROLE") or "")
    if role not in MANAGED_RUNTIME_ROLES:
        return False
    runtime_revision = str(os.environ.get("JOBTOMATIK_RUNTIME_REVISION") or "").lower()
    expected_revision = str(os.environ.get("JOBTOMATIK_EXPECTED_REVISION") or "").lower()
    if not REVISION_RE.fullmatch(runtime_revision) or expected_revision != runtime_revision:
        return False

    status = runtime_lease_status(path, expected_revision=runtime_revision)
    if not status.get("active"):
        return False
    marker = load_marker(path) or {}
    recorded = dict((marker.get("processes") or {}).get(role) or {})
    try:
        return (
            int(recorded.get("pid")) == os.getpid()
            and int(recorded.get("start_ticks")) == int(_process_start_ticks(os.getpid()) or -1)
        )
    except (TypeError, ValueError):
        return False


def clear_owner_bound_marker(path: Path = DEFAULT_MARKER_PATH) -> None:
    """Remove pending or active capability before an ordinary safe restart."""

    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_directory(path.parent)


# Compatibility name retained for callers from earlier PR revisions. It now performs
# dynamic lease validation and never mutates cached Settings at process startup.
def managed_android_lever_runtime_capability_active(
    path: Path = DEFAULT_MARKER_PATH,
) -> bool:
    return lever_supervised_runtime_lease_active(path)


__all__ = [
    "ACTIVE_LEASE_TTL_SECONDS",
    "DEFAULT_MARKER_PATH",
    "LAUNCH_TOKEN_ENV_KEY",
    "MANAGED_RUNTIME_ROLES",
    "MARKER_MODE",
    "MARKER_SCHEMA_VERSION",
    "MARKER_STATE_ACTIVE",
    "MARKER_STATE_PENDING",
    "OWNER_CMDLINE_TOKENS",
    "activate_runtime_lease",
    "clear_owner_bound_marker",
    "create_owner_bound_marker",
    "lever_supervised_runtime_lease_active",
    "load_marker",
    "managed_android_lever_runtime_capability_active",
    "pending_runtime_marker_active",
    "runtime_lease_status",
]
