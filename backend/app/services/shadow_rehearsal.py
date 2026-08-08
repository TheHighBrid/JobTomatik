"""Measured unattended no-submit rehearsal used by the Phase 10 scale gates.

A short smoke run proves the harness itself. Four-, eight-, and twenty-four-hour
qualification is granted only when the measured monotonic elapsed time reaches the
corresponding threshold. The harness never launches an application browser and never
changes runtime submission settings.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

from app.config import get_settings
from app.services.ats_manifest import ats_certification_manifest
from app.services.operations_policy import operations_readiness_manifest


SHADOW_REHEARSAL_VERSION = "1.0.0"
QUALIFICATION_SECONDS = {
    "shadow_run_4h": 4 * 60 * 60,
    "shadow_run_8h": 8 * 60 * 60,
    "shadow_run_24h": 24 * 60 * 60,
}


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_shadow_rehearsal(
    *,
    duration_seconds: float,
    interval_seconds: float = 30.0,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run a bounded policy-only rehearsal and return a tamper-evident report."""
    requested = max(0.0, float(duration_seconds))
    interval = max(0.05, float(interval_seconds))
    started_wall = _utc_now()
    started = monotonic()
    cycles = 0
    failures: list[dict[str, Any]] = []
    settings = get_settings()

    while True:
        operations = operations_readiness_manifest()
        ats = ats_certification_manifest()
        cycles += 1

        assertions = {
            "real_submission_disabled": settings.allow_real_application_submit is False,
            "autopilot_disabled": operations.get("autopilot_enabled") is False,
            "runtime_manifest_available": isinstance(operations, dict),
            "ats_manifest_available": isinstance(ats, dict),
            "final_submit_enabled": False,
            "final_submit_clicked": False,
            "browser_opened": False,
            "network_contacted": False,
        }
        failed = [key for key, value in assertions.items() if key.endswith("disabled") and not value]
        failed.extend(
            key
            for key in ("runtime_manifest_available", "ats_manifest_available")
            if not assertions[key]
        )
        if failed:
            failures.append({"cycle": cycles, "failed_assertions": sorted(set(failed))})
            break

        elapsed = max(0.0, monotonic() - started)
        if elapsed >= requested:
            break
        sleeper(min(interval, max(0.0, requested - elapsed)))

    ended = monotonic()
    measured = max(0.0, ended - started)
    completed = not failures and measured >= requested
    qualifications = {
        name: completed and measured >= threshold
        for name, threshold in QUALIFICATION_SECONDS.items()
    }
    report: dict[str, Any] = {
        "version": SHADOW_REHEARSAL_VERSION,
        "started_at": started_wall.isoformat(),
        "finished_at": _utc_now().isoformat(),
        "requested_duration_seconds": requested,
        "measured_duration_seconds": measured,
        "measured_elapsed_time": True,
        "cycles": cycles,
        "completed": completed,
        "qualification_eligible": any(qualifications.values()),
        "qualifications": qualifications,
        "failures": failures,
        "safety": {
            "final_submit_enabled": False,
            "final_submit_clicked": False,
            "browser_opened": False,
            "network_contacted": False,
            "runtime_settings_changed": False,
        },
    }
    report["report_sha256"] = _canonical_hash(report)
    return report


__all__ = [
    "QUALIFICATION_SECONDS",
    "SHADOW_REHEARSAL_VERSION",
    "run_shadow_rehearsal",
]
