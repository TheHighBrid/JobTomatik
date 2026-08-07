#!/usr/bin/env python3
"""Gracefully retire stale Android Celery workers through Celery remote control.

The Android supervisor uses this helper for two narrowly scoped cleanups:

* legacy foreground workers such as ``celery@localhost`` on Redis DB 0
* orphaned managed workers such as ``jobtomatik-android*@localhost`` on Redis DB 1

The helper never sends an OS signal and never terminates a shell or PRoot session.
"""

from __future__ import annotations

import argparse
import socket
from typing import Iterable

from celery import Celery


DEFAULT_LEGACY_BROKER = "redis://localhost:6379/0"
DEFAULT_MANAGED_BROKER = "redis://localhost:6379/1"
MANAGED_WORKER_PREFIXES = ("jobtomatik-android@", "jobtomatik-android-")


def local_worker_hosts() -> set[str]:
    values = {"localhost", "127.0.0.1", "::1"}
    for value in (socket.gethostname(), socket.getfqdn()):
        normalized = str(value or "").strip().lower()
        if normalized:
            values.add(normalized)
            values.add(normalized.split(".", 1)[0])
    return values


def _is_local_worker_name(name: str, hosts: set[str]) -> bool:
    if "@" not in name:
        return False
    _prefix, host = name.split("@", 1)
    normalized = host.strip().lower()
    return normalized in hosts or normalized.split(".", 1)[0] in hosts


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
        if not name or lowered.startswith(MANAGED_WORKER_PREFIXES):
            continue
        if not _is_local_worker_name(name, hosts):
            continue
        prefix, _host = name.split("@", 1)
        if prefix.strip().lower() == "celery":
            selected.append(name)
    return sorted(set(selected))


def managed_android_worker_names(
    names: Iterable[str],
    *,
    local_hosts: set[str] | None = None,
) -> list[str]:
    """Select only JobTomatik-managed local Android workers."""
    hosts = {value.lower() for value in (local_hosts or local_worker_hosts())}
    selected: list[str] = []
    for raw_name in names:
        name = str(raw_name or "").strip()
        lowered = name.lower()
        if not lowered.startswith(MANAGED_WORKER_PREFIXES):
            continue
        if _is_local_worker_name(name, hosts):
            selected.append(name)
    return sorted(set(selected))


def retire_workers(
    broker_url: str,
    *,
    mode: str = "legacy",
    timeout: float = 1.0,
) -> list[str]:
    client = Celery("jobtomatik-android-runtime-reconciler", broker=broker_url)
    inspector = client.control.inspect(timeout=max(0.2, float(timeout)))
    try:
        pings = inspector.ping() or {}
    except Exception:
        return []

    selector = managed_android_worker_names if mode == "managed" else legacy_local_worker_names
    selected = selector(pings.keys())
    for worker_name in selected:
        try:
            client.control.broadcast(
                "shutdown",
                destination=[worker_name],
                reply=False,
            )
        except Exception:
            continue
    return selected


def retire_legacy_workers(broker_url: str, *, timeout: float = 1.0) -> list[str]:
    return retire_workers(broker_url, mode="legacy", timeout=timeout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", default=DEFAULT_LEGACY_BROKER)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--mode", choices=("legacy", "managed"), default="legacy")
    args = parser.parse_args()

    retired = retire_workers(args.broker, mode=args.mode, timeout=args.timeout)
    if args.mode == "managed":
        marker = "ANDROID_STALE_MANAGED_CELERY_RETIRE_REQUESTED" if retired else "ANDROID_STALE_MANAGED_CELERY_NONE"
        label = "Managed worker"
    else:
        marker = "ANDROID_LEGACY_CELERY_RETIRE_REQUESTED" if retired else "ANDROID_LEGACY_CELERY_NONE"
        label = "Legacy worker"

    print(marker)
    for worker_name in retired:
        print(f"{label}: {worker_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
