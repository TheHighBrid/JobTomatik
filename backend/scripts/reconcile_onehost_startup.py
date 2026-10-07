#!/usr/bin/env python
"""Reconcile OneHost worker-owned state before Celery begins consuming tasks."""

from __future__ import annotations

import json
import os
import sys

from app.database import SessionLocal
from app.services.onehost_startup_recovery import reconcile_onehost_worker_restart


def main() -> int:
    """Reconcile OneHost startup state and return a process exit code."""

    runtime_mode = str(os.getenv("JOBTOMATIK_RUNTIME_MODE") or "").strip().lower()
    if runtime_mode != "onehost":
        print(
            json.dumps(
                {
                    "worker_restart_reconciled": False,
                    "skipped": True,
                    "reason": "not_onehost_runtime",
                },
                sort_keys=True,
            )
        )
        return 0

    db = SessionLocal()
    try:
        result = reconcile_onehost_worker_restart(db)
        db.commit()
    except Exception as exc:
        db.rollback()
        print(
            json.dumps(
                {
                    "worker_restart_reconciled": False,
                    "error": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        db.close()

    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
