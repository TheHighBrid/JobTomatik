from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class SchedulerDispatchOut(BaseModel):
    queued: bool
    user_id: int
    celery_task_id: str | None = None
    scheduler_state: str
    preview: dict[str, Any]
