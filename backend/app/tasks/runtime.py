"""Minimal end-to-end canary tasks for the managed Android runtime."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from app.celery_app import celery_app
from app.config import get_settings


def _redis_database(url: str) -> int | None:
    try:
        path = (urlsplit(str(url or "")).path or "").strip("/")
        return int(path or "0")
    except (TypeError, ValueError):
        return None


@celery_app.task(
    name="app.tasks.runtime.application_queue_canary",
    queue="applications",
)
def application_queue_canary(expected_revision: str = "") -> dict:
    """Prove producer -> applications queue -> worker -> result-backend continuity."""
    revision = str(os.getenv("JOBTOMATIK_RUNTIME_REVISION", "") or "").strip()
    expected = str(expected_revision or "").strip()
    settings = get_settings()
    return {
        "ok": bool(revision) and (not expected or revision == expected),
        "revision": revision,
        "expected_revision": expected,
        "worker_pid": os.getpid(),
        "redis_db": _redis_database(settings.redis_url),
    }


__all__ = ["application_queue_canary"]
