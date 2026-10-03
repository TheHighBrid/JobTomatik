"""Runtime-only telemetry for the Day 36 four-hour shadow endurance gate.

The integration enriches the already-retained Phase 11 observability snapshots with
process memory measurements. It does not schedule work, mutate campaign policy, touch
adapter maturity, or grant submission/outreach authority.
"""

from __future__ import annotations

import os
import resource
from functools import wraps
from typing import Any


DAY36_ENDURANCE_TELEMETRY_VERSION = "day36-shadow-endurance-v1"
_INSTALLED = False


def _proc_status_kib() -> dict[str, int | None]:
    values: dict[str, int | None] = {"rss_kib": None, "peak_rss_kib": None}
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    values["rss_kib"] = int(line.split()[1])
                elif line.startswith("VmHWM:"):
                    values["peak_rss_kib"] = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return values


def process_memory_snapshot() -> dict[str, Any]:
    """Return bounded process-memory telemetry without environment or secret data."""

    proc = _proc_status_kib()
    rss_kib = proc["rss_kib"]
    peak_kib = proc["peak_rss_kib"]
    source = "proc_status" if rss_kib is not None or peak_kib is not None else "rusage"

    if peak_kib is None:
        try:
            maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            # Linux/Android report KiB. Darwin reports bytes, but Day 36 production is
            # Android/Linux. Keep a conservative conversion for local macOS tests.
            if os.uname().sysname.lower() == "darwin":
                maximum //= 1024
            peak_kib = maximum
        except (OSError, ValueError, AttributeError):
            peak_kib = None

    return {
        "version": DAY36_ENDURANCE_TELEMETRY_VERSION,
        "source": source,
        "rss_kib": rss_kib,
        "peak_rss_kib": peak_kib,
        "pid": os.getpid(),
    }


def install_day36_endurance_runtime() -> None:
    """Idempotently enrich Phase 11 observability snapshots in the shadow worker."""

    global _INSTALLED
    if _INSTALLED:
        return

    from app.services import full_stack_shadow

    original = full_stack_shadow._observability_report
    if getattr(original, "_day36_endurance_wrapper", False):
        _INSTALLED = True
        return

    @wraps(original)
    def instrumented(db, user_id: int, *, window_hours: int):
        report = dict(original(db, user_id, window_hours=window_hours) or {})
        report["day36_runtime_memory"] = process_memory_snapshot()
        report["day36_endurance_telemetry_version"] = DAY36_ENDURANCE_TELEMETRY_VERSION
        return report

    instrumented._day36_endurance_wrapper = True
    instrumented._day36_endurance_original = original
    full_stack_shadow._observability_report = instrumented
    _INSTALLED = True


__all__ = [
    "DAY36_ENDURANCE_TELEMETRY_VERSION",
    "install_day36_endurance_runtime",
    "process_memory_snapshot",
]
