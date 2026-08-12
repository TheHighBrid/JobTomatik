#!/usr/bin/env python3
"""Prove the exact physical Android runtime before any shadow qualification canary."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402
from app.services.android_worker_canary import (  # noqa: E402
    WORKER_CANARY_RECEIPT_FILENAME,
    validate_worker_canary_receipt,
)
from app.services.certification_scale import current_revision  # noqa: E402
from app.services.runtime_acceptance import (  # noqa: E402
    runtime_acceptance_path,
    runtime_dir,
    runtime_fingerprint,
    write_receipt,
)


REQUIRED_WORKER_QUEUES = "applications,celery,followup,scraping"


def _http_json(url: str, timeout: float = 3.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "JobTomatik-Android-Acceptance/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected JSON object from {url}")
    return payload


def _http_text(url: str, timeout: float = 3.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "JobTomatik-Android-Acceptance/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _pid(path: Path) -> int:
    value = int(path.read_text(encoding="utf-8").strip())
    if value <= 0:
        raise RuntimeError(f"Invalid PID in {path}")
    return value


def _cmdline(pid: int) -> str:
    return (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode(
        "utf-8", errors="replace"
    )


def _assert_tokens(label: str, pid: int, *tokens: str) -> dict[str, Any]:
    command = _cmdline(pid)
    missing = [token for token in tokens if token and token not in command]
    if missing:
        raise RuntimeError(f"{label} process identity mismatch; missing tokens: {missing}")
    return {"pid": pid, "cmdline": command[:1200]}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"Expected object in {path}")
    return payload


def _worker_identity_tokens(revision: str) -> tuple[str, ...]:
    return (
        "celery",
        "app.celery_app",
        "worker",
        f"jobtomatik-android-{revision[:12]}@",
        "-Q",
        REQUIRED_WORKER_QUEUES,
    )


def _worker_acceptance(
    revision: str,
    worker_pid: int,
    *,
    directory: Path | None = None,
) -> dict[str, Any]:
    """Validate the exact startup round-trip proof without queueing duplicate work.

    The Android production worker intentionally uses a solo pool and consumes long-running
    application, discovery, follow-up, and shadow-recovery tasks. Runtime acceptance must
    not confuse "busy" with "dead" by dispatching another health task after Beat has begun
    scheduling real work. The manager therefore proves producer -> Redis DB1 -> applications
    queue -> exact worker once during startup, before Beat is admitted, and persists a receipt
    bound to the worker PID and /proc start token. Later acceptance verifies that durable proof
    together with the live worker command line instead of requiring the worker to be idle.
    """

    runtime_directory = directory or runtime_dir()
    status = validate_worker_canary_receipt(
        runtime_directory / WORKER_CANARY_RECEIPT_FILENAME,
        expected_revision=revision,
        expected_worker_pid=worker_pid,
        required_queues=REQUIRED_WORKER_QUEUES.split(","),
    )
    if not status.get("ok"):
        blockers = ",".join(status.get("blockers") or []) or "unknown"
        raise RuntimeError(f"Android worker startup canary receipt failed: {blockers}")
    receipt = dict(status.get("receipt") or {})
    return {
        "worker_pid": worker_pid,
        "worker_start_token": status.get("worker_start_token"),
        "declared_queues": REQUIRED_WORKER_QUEUES.split(","),
        "startup_canary_receipt": receipt,
        "queue_canary": dict(receipt.get("queue_canary") or {}),
        "ownership_proof": (
            "exact_pid_plus_process_start_token_plus_revision_hostname_plus_queue_cmdline_"
            "plus_startup_db1_round_trip_receipt"
        ),
    }


def run_acceptance() -> dict[str, Any]:
    directory = runtime_dir()
    revision = current_revision()
    settings = get_settings()
    if revision == "unknown":
        raise RuntimeError("Runtime revision is unknown")
    if settings.allow_real_application_submit is not False:
        raise RuntimeError("Real application submission must remain disabled")
    if settings.allow_real_followup_send is not False:
        raise RuntimeError("Real recruiter/follow-up sending must remain disabled")

    manifest_path = directory / "frontend-artifacts" / revision / "jobtomatik-frontend-manifest.json"
    manifest = _load_json(manifest_path)
    if manifest.get("revision") != revision or manifest.get("artifact_type") != "jobtomatik-static-frontend":
        raise RuntimeError("Static frontend artifact revision/identity mismatch")

    frontend_identity = _http_json("http://127.0.0.1:3000/__jobtomatik_frontend_identity")
    if (
        frontend_identity.get("runtime") != "static_artifact"
        or frontend_identity.get("revision") != revision
        or frontend_identity.get("dist_tree_sha256") != manifest.get("dist_tree_sha256")
        or frontend_identity.get("final_submit_allowed") is not False
        or frontend_identity.get("outreach_authorized") is not False
    ):
        raise RuntimeError("Static frontend HTTP identity attestation failed")
    deep_route = _http_text("http://127.0.0.1:3000/shadow-campaigns")
    if '<div id="root"' not in deep_route and "<div id='root'" not in deep_route:
        raise RuntimeError("Static frontend SPA deep-route fallback failed")

    api_identity = _http_json("http://127.0.0.1:8010/api/system/runtime-identity")
    if (
        api_identity.get("revision") != revision
        or api_identity.get("expected_revision") != revision
        or api_identity.get("role") != "api"
        or api_identity.get("deployment_attested") is not True
        or api_identity.get("submission_authorized") is not False
        or api_identity.get("outreach_authorized") is not False
    ):
        raise RuntimeError("API runtime identity attestation failed")

    cdp = _http_json("http://127.0.0.1:9222/json/version")
    if not cdp.get("webSocketDebuggerUrl"):
        raise RuntimeError("External Termux Chromium CDP is unavailable")

    api_pid = _pid(directory / "api.pid")
    worker_pid = _pid(directory / "celery.pid")
    beat_pid = _pid(directory / "celery-beat.pid")
    frontend_pid = _pid(directory / "frontend.pid")
    process_identity = {
        "api": _assert_tokens("api", api_pid, "uvicorn", "app.main:app", "--port", "8010"),
        "worker": _assert_tokens(
            "worker",
            worker_pid,
            *_worker_identity_tokens(revision),
        ),
        "beat": _assert_tokens("beat", beat_pid, "celery", "app.celery_app", "beat"),
        "frontend": _assert_tokens(
            "frontend",
            frontend_pid,
            "serve_static_frontend.py",
            "--revision",
            revision,
            "--port",
            "3000",
        ),
    }

    beat_identity = _load_json(directory / "celery-beat-identity.json")
    if (
        beat_identity.get("revision") != revision
        or beat_identity.get("expected_revision") != revision
        or beat_identity.get("role") != "beat"
        or beat_identity.get("deployment_attested") is not True
        or beat_identity.get("submission_authorized") is not False
        or beat_identity.get("outreach_authorized") is not False
    ):
        raise RuntimeError("Celery Beat identity receipt failed")

    worker = _worker_acceptance(revision, worker_pid, directory=directory)
    fingerprint = runtime_fingerprint()
    if any(
        not (item.get("pid") and item.get("start_token"))
        for item in (fingerprint.get("processes") or {}).values()
    ):
        raise RuntimeError("Runtime fingerprint could not attest every managed process start identity")

    return {
        "version": 1,
        "status": "pass",
        "revision": revision,
        "runtime_mode": "android_managed",
        "runtime_fingerprint_sha256": fingerprint["sha256"],
        "runtime_fingerprint": fingerprint,
        "frontend": {
            "runtime": "static_artifact",
            "revision": revision,
            "dist_tree_sha256": manifest.get("dist_tree_sha256"),
            "package_lock_sha256": manifest.get("package_lock_sha256"),
            "http_identity": frontend_identity,
            "spa_deep_route": True,
        },
        "backend": {
            "api_identity": api_identity,
            "worker": worker,
            "beat_identity": beat_identity,
            "redis_db": 1,
        },
        "browser": {
            "cdp_ready": True,
            "browser": cdp.get("Browser"),
        },
        "process_identity": process_identity,
        "safety": {
            "real_submission_disabled": True,
            "final_submit_allowed": False,
            "outreach_authorized": False,
        },
    }


def main() -> int:
    try:
        payload = run_acceptance()
        receipt = write_receipt(runtime_acceptance_path(), payload)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        print(
            "ANDROID_RUNTIME_ACCEPTANCE=PASS "
            f"revision={receipt['revision']} fingerprint={receipt['runtime_fingerprint_sha256']}"
        )
        return 0
    except Exception as exc:
        failure = {
            "version": 1,
            "status": "fail",
            "revision": current_revision(),
            "error": str(exc)[:1800],
            "safety": {
                "real_submission_disabled": get_settings().allow_real_application_submit is False,
                "final_submit_allowed": False,
                "outreach_authorized": False,
            },
        }
        write_receipt(runtime_acceptance_path(), failure)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        print(f"ANDROID_RUNTIME_ACCEPTANCE=FAIL reason={failure['error']}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
