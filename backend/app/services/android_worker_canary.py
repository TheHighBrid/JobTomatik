"""Durable exact-worker startup canary receipts for the managed Android runtime."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


WORKER_CANARY_RECEIPT_FILENAME = "celery-application-canary.json"


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _proc_start_token(pid: int, proc_root: Path = Path("/proc")) -> str | None:
    try:
        stat = (proc_root / str(int(pid)) / "stat").read_text(encoding="utf-8")
        remainder = stat.rsplit(") ", 1)[1]
        fields = remainder.split()
        return fields[19]
    except (OSError, TypeError, ValueError, IndexError):
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def write_worker_canary_receipt(
    path: Path,
    *,
    payload: dict[str, Any],
    expected_revision: str,
    expected_worker_pid: int,
    declared_queues: Iterable[str],
    proc_root: Path = Path("/proc"),
) -> dict[str, Any]:
    """Persist a startup round-trip proof tied to the exact live worker process."""

    revision = str(expected_revision or "").strip().lower()
    worker_pid = int(expected_worker_pid)
    queues = [str(item).strip() for item in declared_queues if str(item).strip()]
    start_token = _proc_start_token(worker_pid, proc_root)
    if not revision or worker_pid <= 0 or not queues or not start_token:
        raise RuntimeError("Cannot bind Android worker canary receipt to process identity")

    valid = (
        payload.get("ok") is True
        and payload.get("revision") == revision
        and payload.get("expected_revision") == revision
        and _int_or_none(payload.get("worker_pid")) == worker_pid
        and _int_or_none(payload.get("redis_db")) == 1
        and payload.get("runtime_expected_revision") == revision
        and payload.get("runtime_role") == "worker"
        and payload.get("deployment_attested") is True
        and bool(payload.get("runtime_identity_sha256"))
    )
    if not valid:
        raise RuntimeError("Android worker startup canary payload is not exactly attested")

    output = {
        "version": 1,
        "status": "pass",
        "created_at": _iso_now(),
        "revision": revision,
        "expected_revision": revision,
        "redis_db": 1,
        "worker_pid": worker_pid,
        "worker_start_token": start_token,
        "runtime_role": "worker",
        "deployment_attested": True,
        "runtime_identity_sha256": payload.get("runtime_identity_sha256"),
        "declared_queues": queues,
        "queue_canary": dict(payload),
        "proof": "startup_exact_worker_db1_round_trip",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return output


def validate_worker_canary_receipt(
    path: Path,
    *,
    expected_revision: str,
    expected_worker_pid: int,
    required_queues: Iterable[str],
    proc_root: Path = Path("/proc"),
) -> dict[str, Any]:
    """Validate the startup proof without dispatching work to a potentially busy solo worker."""

    payload = _read_json(path)
    revision = str(expected_revision or "").strip().lower()
    worker_pid = int(expected_worker_pid)
    queues = [str(item).strip() for item in required_queues if str(item).strip()]
    current_start_token = _proc_start_token(worker_pid, proc_root)
    queue_canary = dict((payload or {}).get("queue_canary") or {})

    checks = {
        "receipt_present": payload is not None,
        "receipt_passed": bool(payload and payload.get("status") == "pass"),
        "revision_matches": bool(payload and payload.get("revision") == revision),
        "expected_revision_matches": bool(payload and payload.get("expected_revision") == revision),
        "worker_pid_matches": bool(payload and _int_or_none(payload.get("worker_pid")) == worker_pid),
        "worker_start_identity_matches": bool(
            payload
            and current_start_token
            and payload.get("worker_start_token") == current_start_token
        ),
        "redis_db1": bool(payload and _int_or_none(payload.get("redis_db")) == 1),
        "runtime_role_worker": bool(payload and payload.get("runtime_role") == "worker"),
        "deployment_attested": bool(payload and payload.get("deployment_attested") is True),
        "runtime_identity_digest_present": bool(payload and payload.get("runtime_identity_sha256")),
        "declared_queues_match": bool(payload and list(payload.get("declared_queues") or []) == queues),
        "queue_canary_revision_matches": bool(queue_canary.get("revision") == revision),
        "queue_canary_expected_revision_matches": bool(queue_canary.get("expected_revision") == revision),
        "queue_canary_worker_pid_matches": _int_or_none(queue_canary.get("worker_pid")) == worker_pid,
        "queue_canary_redis_db1": _int_or_none(queue_canary.get("redis_db")) == 1,
        "queue_canary_runtime_expected_revision_matches": bool(
            queue_canary.get("runtime_expected_revision") == revision
        ),
        "queue_canary_runtime_role_worker": bool(queue_canary.get("runtime_role") == "worker"),
        "queue_canary_deployment_attested": bool(queue_canary.get("deployment_attested") is True),
        "queue_canary_identity_digest_present": bool(queue_canary.get("runtime_identity_sha256")),
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return {
        "ok": not blockers,
        "checks": checks,
        "blockers": blockers,
        "receipt": payload or {},
        "worker_start_token": current_start_token,
    }


__all__ = [
    "WORKER_CANARY_RECEIPT_FILENAME",
    "validate_worker_canary_receipt",
    "write_worker_canary_receipt",
]
