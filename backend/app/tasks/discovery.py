"""Continuous read-only discovery scheduler.

This task intentionally does not evaluate or enable application autopilot. It refreshes
explicitly configured discovery sources for users who opted into auto-search, applies
bounded per-source cooldowns, and delegates persistence to the existing discovery task.
"""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.user import User
from app.services.discovery_scheduler import DISCOVERY_POLICY_VERSION, apply_source_backoff
from app.services.operations_settings import get_operations_settings
from app.services.scheduler_policy import build_search_plan, scheduler_settings
from app.tasks.scraping import run_job_search


def _run_continuous_discovery(db) -> dict[str, Any]:
    operations = get_operations_settings()
    if operations.global_kill_switch:
        return {
            "skipped": True,
            "reason": "global_kill_switch",
            "users_considered": 0,
            "searches_queued": 0,
            "backoff_blocked": 0,
            "autopilot_enabled": operations.autopilot_enabled,
            "policy_version": DISCOVERY_POLICY_VERSION,
        }

    users = db.query(User).filter(User.is_active == True).all()
    cycles: list[dict[str, Any]] = []
    searches_queued = 0
    backoff_blocked = 0

    for user in users:
        settings = scheduler_settings(user)
        cycle: dict[str, Any] = {
            "user_id": int(user.id),
            "queued": False,
            "reason": None,
            "task_id": None,
            "blocked_sources": [],
        }

        if not settings.get("scheduler_policy_current"):
            cycle["reason"] = "scheduler_policy_upgrade_required"
            cycles.append(cycle)
            continue
        if not bool(settings.get("auto_search_enabled", False)):
            cycle["reason"] = "auto_search_disabled"
            cycles.append(cycle)
            continue

        plan = build_search_plan(user)
        if not plan.get("ready"):
            cycle["reason"] = str(plan.get("reason_code") or "search_plan_blocked")
            cycles.append(cycle)
            continue

        bounded = apply_source_backoff(
            db,
            user_id=int(user.id),
            search_params=dict(plan["search_params"]),
        )
        cycle["blocked_sources"] = list(bounded.get("blocked_sources") or [])
        if not bounded.get("ready"):
            cycle["reason"] = "all_sources_in_backoff"
            backoff_blocked += len(cycle["blocked_sources"])
            cycles.append(cycle)
            continue

        search_params = {
            **dict(bounded["search_params"]),
            "_origin": "scheduler",
            "_discovery_policy_version": DISCOVERY_POLICY_VERSION,
        }
        task = run_job_search.delay(user_id=int(user.id), search_params=search_params)
        cycle["queued"] = True
        cycle["reason"] = "continuous_discovery_queued"
        cycle["task_id"] = getattr(task, "id", None)
        cycle["active_task_count"] = int(bounded.get("active_task_count") or 0)
        searches_queued += 1
        backoff_blocked += len(cycle["blocked_sources"])
        cycles.append(cycle)

    return {
        "skipped": False,
        "reason": "continuous_discovery_completed",
        "users_considered": len(users),
        "searches_queued": searches_queued,
        "backoff_blocked": backoff_blocked,
        "autopilot_enabled": operations.autopilot_enabled,
        "policy_version": DISCOVERY_POLICY_VERSION,
        "cycles": cycles,
    }


@celery_app.task(name="app.tasks.discovery.run_continuous_discovery", queue="scraping")
def run_continuous_discovery():
    db = SessionLocal()
    try:
        return _run_continuous_discovery(db)
    finally:
        db.close()


__all__ = ["_run_continuous_discovery", "run_continuous_discovery"]
