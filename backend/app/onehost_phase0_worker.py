"""Celery application entrypoint for the synthetic Phase 0 integration proof.

The normal Celery application and normal application task remain unchanged. This
module is selected only by docker-compose.onehost-api-celery.yml. It patches the
single browser call used by submit_application_task after importing the real
Celery app so the proof exercises FastAPI, Redis, Celery, PostgreSQL, the real
application task/state machine, and the current v3 filler primitives without
routing through retained Android/CDP handoff code.
"""

from __future__ import annotations

import os

if str(os.getenv("JOBTOMATIK_ONEHOST_PHASE0_PROOF") or "").strip() != "1":
    raise RuntimeError("The Phase 0 proof worker cannot run outside its synthetic proof environment")

from app.celery_app import celery_app  # noqa: E402
from app.services.onehost_phase0_fixture_runtime import (  # noqa: E402
    fill_and_submit_application as phase0_fill_and_submit_application,
)
from app.tasks import applications as application_tasks  # noqa: E402


application_tasks.fill_and_submit_application = phase0_fill_and_submit_application

__all__ = ["celery_app"]
