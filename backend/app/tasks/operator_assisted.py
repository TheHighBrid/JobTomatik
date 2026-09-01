"""Prepare a filled retained ATS page without granting automated final-submit authority."""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.services.operator_assisted_handoff_integration import (
    install_operator_assisted_handoff_integration,
    operator_prepare_scope,
)
from app.services.operator_assisted_submission import (
    OperatorAssistedSubmissionError,
    build_operator_assisted_preflight,
)
from app.services.supervised_target_identity import (
    persist_supervised_target_metadata,
    resolve_supervised_target_metadata,
)
from app.tasks.applications import submit_application_task


install_operator_assisted_handoff_integration()


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


@celery_app.task(
    bind=True,
    name="app.tasks.operator_assisted.prepare_operator_assisted_application_task",
    queue="applications",
)
def prepare_operator_assisted_application_task(self, application_id: int):
    """Run one fail-safe fill-only pass and retain the exact ready-to-submit page."""

    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).first()
        if not application:
            return {"error": "Application not found", "success": False}
        user = db.query(User).filter(User.id == application.user_id).first()
        job = db.query(Job).filter(Job.id == application.job_id).first()
        if not user or not job:
            return {"error": "Application user or job is missing", "success": False}

        target_metadata = _run_async(resolve_supervised_target_metadata(job))
        if target_metadata:
            persist_supervised_target_metadata(job, target_metadata)
        preflight = build_operator_assisted_preflight(
            db,
            application,
            user,
            job,
            target_metadata=target_metadata,
        )
        if not preflight["ready"]:
            return {
                "success": False,
                "requires_manual_review": False,
                "operator_assisted": True,
                "error": "Operator-assisted preparation is blocked: "
                + ", ".join(preflight["blockers"]),
                "blockers": list(preflight["blockers"]),
            }
        db.commit()
    except OperatorAssistedSubmissionError as exc:
        db.rollback()
        return {
            "success": False,
            "operator_assisted": True,
            "error": str(exc),
        }
    finally:
        db.close()

    try:
        with operator_prepare_scope(target_metadata or {}):
            result = submit_application_task.run(application_id, dry_run=True)
        if isinstance(result, dict):
            result = dict(result)
            result["operator_assisted"] = True
            result["automated_submission_authorized"] = False
            result["final_submit_clicked_by_jobtomatik"] = False
        return result
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30, max_retries=1)


__all__ = ["prepare_operator_assisted_application_task"]
