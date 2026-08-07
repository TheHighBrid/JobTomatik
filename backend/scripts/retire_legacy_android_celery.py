#!/usr/bin/env python3
"""Gracefully retire pre-supervisor Android Celery workers on the legacy broker.

Older manual setup instructions started a foreground worker with Celery's default
hostname (typically ``celery@localhost``) on Redis DB 0. It can remain alive after a
Git pull and continue executing the Python modules that were imported at its original
startup. The managed Android runtime now uses Redis DB 1, but we also ask those exact
legacy local workers to shut down so old queued retries cannot keep mutating runtime
state.

This script uses Celery's remote-control channel. It never sends an OS signal, never
matches terminal processes, and never terminates a shell or PRoot session.
"""

from __future__ import annotations

import argparse
import socket
from typing import Iterable

from celery import Celery


DEFAULT_LEGACY_BROKER = "redis://localhost:6379/0"
MANAGED_WORKER_PREFIX = "jobtomatik-android@"


def local_worker_hosts() -> set[str]:
    values = {"localhost", "127.0.0.1", "::1"}
    for value in (socket.gethostname(), socket.getfqdn()):
        normalized = str(value or "").strip().lower()
        if normalized:
            values.add(normalized)
            values.add(normalized.split(".", 1)[0])
    return values


def legacy_local_worker_names(
    names: Iterable[str],
    *,
    local_hosts: set[str] | None = None,
) -> list[str]:
    """Select only default-hostname local workers from the old manual workflow."""
    hosts = {value.lower() for value in (local_hosts or local_worker_hosts())}
    selected: list[str] = []
    for raw_name in names:
        name = str(raw_name or "").strip()
        lowered = name.lower()
        if not name or lowered.startswith(MANAGED_WORKER_PREFIX):
            continue
        if "@" not in name:
            continue
        prefix, host = name.split("@", 1)
        host = host.strip().lower()
        if prefix.strip().lower() != "celery":
            continue
        if host in hosts or host.split(".", 1)[0] in hosts:
            selected.append(name)
    return sorted(set(selected))


def retire_legacy_workers(broker_url: str, *, timeout: float = 1.0) -> list[str]:
    client = Celery("jobtomatik-android-runtime-reconciler", broker=broker_url)
    inspector = client.control.inspect(timeout=max(0.2, float(timeout)))
    try:
        pings = inspector.ping() or {}
    except Exception:
        return []

    legacy = legacy_local_worker_names(pings.keys())
    for worker_name in legacy:
        try:
            client.control.broadcast(
                "shutdown",
                destination=[worker_name],
                reply=False,
            )
        except Exception:
            # Broker isolation already prevents this worker from receiving new DB 1
            # tasks. Shutdown is best-effort cleanup for old DB 0 retries.
            continue
    return legacy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default=DEFAULT_LEGACY_BROKER)
    parser.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args()

    retired = retire_legacy_workers(args.broker, timeout=args.timeout)
    if retired:
        print("ANDROID_LEGACY_CELERY_RETIRE_REQUESTED")
        for worker_name in retired:
            print(f"Legacy worker: {worker_name}")
    else:
        print("ANDROID_LEGACY_CELERY_NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
