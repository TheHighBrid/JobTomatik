"""Machine-readable Android runtime and shadow-canary admission receipts."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.certification_scale import current_revision, ensure_aware

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_DIR = BACKEND_ROOT / ".runtime"
RUNTIME_ACCEPTANCE_FILENAME = "android-runtime-acceptance.json"
CANARY_RECEIPT_PREFIX = "shadow-qualification-canary-user-"
DEFAULT_RECEIPT_MAX_AGE_SECONDS = 60 * 60


def runtime_dir() -> Path:
    return Path(os.environ.get("JOBTOMATIK_RUNTIME_DIR", DEFAULT_RUNTIME_DIR)).resolve()


def runtime_acceptance_path() -> Path:
    return runtime_dir() / RUNTIME_ACCEPTANCE_FILENAME


def canary_receipt_path(user_id: int) -> Path:
    return runtime_dir() / f"{CANARY_RECEIPT_PREFIX}{int(user_id)}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ensure_aware(parsed)


def _fresh(payload: dict[str, Any], *, max_age_seconds: int) -> bool:
    created = _parse_time(payload.get("created_at"))
    if created is None:
        return False
    age = (datetime.now(timezone.utc) - created).total_seconds()
    return 0 <= age <= max(1, int(max_age_seconds))


def _proc_start_token(pid: int, proc_root: Path = Path("/proc")) -> str | None:
    try:
        stat = (proc_root / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # Linux /proc/<pid>/stat field 22 is process start time. The command field can
    # contain spaces inside parentheses, so split only after the final ') '.
    try:
        remainder = stat.rsplit(") ", 1)[1]
        fields = remainder.split()
        return fields[19]
    except (IndexError, ValueError):
        return None


def _pid_file_value(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def _frontend_manifest() -> dict[str, Any] | None:
    revision = current_revision()
    path = runtime_dir() / "frontend-artifacts" / revision / "jobtomatik-frontend-manifest.json"
    return _read_json(path)


def runtime_fingerprint(proc_root: Path = Path("/proc")) -> dict[str, Any]:
    """Return the exact process/artifact identity that invalidates on restart/deploy."""

    directory = runtime_dir()
    roles = {
        "api": directory / "api.pid",
        "worker": directory / "celery.pid",
        "beat": directory / "celery-beat.pid",
        "frontend": directory / "frontend.pid",
    }
    processes: dict[str, Any] = {}
    for role, path in roles.items():
        pid = _pid_file_value(path)
        processes[role] = {
            "pid": pid,
            "start_token": _proc_start_token(pid, proc_root) if pid else None,
        }

    manifest = _frontend_manifest() or {}
    fingerprint_payload = {
        "revision": current_revision(),
        "frontend_dist_sha256": manifest.get("dist_tree_sha256"),
        "frontend_package_lock_sha256": manifest.get("package_lock_sha256"),
        "processes": processes,
    }
    canonical = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"))
    return {
        **fingerprint_payload,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def write_receipt(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = {**payload, "created_at": payload.get("created_at") or _iso_now()}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return output


def runtime_acceptance_status(*, max_age_seconds: int = DEFAULT_RECEIPT_MAX_AGE_SECONDS) -> dict[str, Any]:
    payload = _read_json(runtime_acceptance_path())
    fingerprint = runtime_fingerprint()
    revision = current_revision()
    checks = {
        "receipt_present": payload is not None,
        "receipt_fresh": bool(payload and _fresh(payload, max_age_seconds=max_age_seconds)),
        "revision_matches": bool(payload and payload.get("revision") == revision),
        "runtime_fingerprint_matches": bool(
            payload and payload.get("runtime_fingerprint_sha256") == fingerprint.get("sha256")
        ),
        "frontend_static_artifact": bool(
            payload and payload.get("frontend", {}).get("runtime") == "static_artifact"
        ),
        "real_submission_disabled": bool(
            payload and payload.get("safety", {}).get("real_submission_disabled") is True
        ),
        "final_submit_disabled": bool(
            payload and payload.get("safety", {}).get("final_submit_allowed") is False
        ),
        "outreach_disabled": bool(
            payload and payload.get("safety", {}).get("outreach_authorized") is False
        ),
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not blockers,
        "checks": checks,
        "blockers": blockers,
        "revision": revision,
        "runtime_fingerprint": fingerprint,
        "receipt": payload or {},
    }


def canary_receipt_status(
    user_id: int,
    *,
    max_age_seconds: int = DEFAULT_RECEIPT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    payload = _read_json(canary_receipt_path(user_id))
    runtime = runtime_acceptance_status(max_age_seconds=max_age_seconds)
    fingerprint = runtime.get("runtime_fingerprint") or {}
    revision = current_revision()
    checks = {
        "receipt_present": payload is not None,
        "receipt_fresh": bool(payload and _fresh(payload, max_age_seconds=max_age_seconds)),
        "user_matches": bool(payload and int(payload.get("user_id") or 0) == int(user_id)),
        "revision_matches": bool(payload and payload.get("revision") == revision),
        "runtime_acceptance_ready": bool(runtime.get("ok")),
        "runtime_fingerprint_matches": bool(
            payload and payload.get("runtime_fingerprint_sha256") == fingerprint.get("sha256")
        ),
        "application_path_observed": bool(payload and payload.get("application_path_observed") is True),
        "certification_eligible_false": bool(payload and payload.get("certification_eligible") is False),
        "final_submit_disabled": bool(payload and payload.get("safety", {}).get("final_submit_allowed") is False),
        "real_submission_disabled": bool(payload and payload.get("safety", {}).get("real_submission_disabled") is True),
        "outreach_disabled": bool(payload and payload.get("safety", {}).get("outreach_authorized") is False),
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not blockers,
        "checks": checks,
        "blockers": blockers,
        "revision": revision,
        "receipt": payload or {},
        "runtime_acceptance": runtime,
    }
