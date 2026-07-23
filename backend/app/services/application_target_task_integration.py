from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any, Coroutine, Dict, Optional

from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
    ManualReviewStatus,
    ManualReviewTask,
)
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.services.application_state import normalize_state, transition_application_state
from app.services.application_target import (
    initialize_application_target,
    mark_target_resolving,
    record_application_target,
    record_target_failure,
    record_target_requires_human,
)
from app.services.application_target_resolver import resolve_application_target_with_browser


_INSTALLED = False
_ORIGINAL_RUN = None
_ORIGINAL_ENSURE_APPLICATION_METHOD = None
_ACTIVE_APPLICATION_TARGET: ContextVar[Optional[str]] = ContextVar(
    "jobtomatik_active_application_target",
    default=None,
)


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def _restore_retryable_state(db, app: Application) -> None:
    """Move an older failed attempt back into a legal retry state."""
    if normalize_state(app.automation_state) != ApplicationAutomationState.failed.value:
        return
    transition_application_state(
        db,
        app,
        ApplicationAutomationState.ready_to_apply,
        "application_target_retry_started",
        {"previous_target_status": app.application_target_status},
    )


def _apply_target_review_copy(db, app: Application, result: Dict[str, Any], reason_value: str) -> None:
    """Replace the generic question-review copy with the doorway instruction."""
    matching_item = next(
        (
            item
            for item in result.get("review_items") or []
            if str(item.get("reason_code") or "") == reason_value
        ),
        None,
    )
    if not matching_item:
        return
    review = (
        db.query(ManualReviewTask)
        .filter(
            ManualReviewTask.application_id == app.id,
            ManualReviewTask.reason_code == reason_value,
            ManualReviewTask.status.in_([
                ManualReviewStatus.open.value,
                ManualReviewStatus.in_progress.value,
            ]),
        )
        .order_by(ManualReviewTask.created_at.desc(), ManualReviewTask.id.desc())
        .first()
    )
    if not review:
        return
    review.summary = str(
        matching_item.get("summary")
        or result.get("error")
        or "One browser navigation step requires your input."
    )
    review.details = {
        **dict(review.details or {}),
        "stage": "application_target_resolution",
        "source_listing_url": result.get("source_listing_url"),
    }


def _prepare_target(application_tasks, application_id: int) -> Dict[str, Any]:
    db = application_tasks.SessionLocal()
    source_url = ""
    try:
        app = db.query(Application).filter(Application.id == application_id).first()
        if not app:
            return {"terminal_result": {"error": "Application not found"}}
        job = db.query(Job).filter(Job.id == app.job_id).first()
        if not job:
            return {"terminal_result": {"error": "Job not found"}}

        source_url = (app.source_listing_url or job.url or "").strip()
        target_url = initialize_application_target(db, app, job)
        if target_url:
            _restore_retryable_state(db, app)
            db.commit()
            return {"target_url": target_url, "source_url": source_url}
        if not source_url:
            db.commit()
            return {"target_url": None, "source_url": source_url}

        _restore_retryable_state(db, app)
        mark_target_resolving(db, app, source_url=source_url)
        db.commit()
    finally:
        db.close()

    result = _run_async(resolve_application_target_with_browser(source_url))

    db = application_tasks.SessionLocal()
    try:
        app = db.query(Application).filter(Application.id == application_id).with_for_update().first()
        if not app:
            return {"terminal_result": {"error": "Application not found"}}
        job = db.query(Job).filter(Job.id == app.job_id).first()
        if not job:
            return {"terminal_result": {"error": "Job not found"}}

        app.automation_log = list(result.get("log") or [])
        target_url = str(result.get("application_target_url") or "")
        if result.get("success") and target_url:
            record_application_target(
                db,
                app,
                target_url=target_url,
                method=str(result.get("resolution_method") or "browser_navigation"),
                metadata={"resolver_log_entries": len(result.get("log") or [])},
            )
            db.commit()
            return {"target_url": target_url, "source_url": source_url}

        if result.get("requires_manual_review"):
            record_target_requires_human(
                db,
                app,
                metadata={
                    "source_listing_url": source_url,
                    "handoff_stage": "application_target_resolution",
                },
            )
            app.status = ApplicationStatus.pending
            reason_code = application_tasks._create_result_review_tasks(
                db,
                app,
                result,
                "target_resolution",
                source_url,
            )
            reason_value = str(getattr(reason_code, "value", reason_code))
            _apply_target_review_copy(db, app, result, reason_value)
            db.add(Notification(
                user_id=app.user_id,
                type=NotificationType.system,
                title=f"Application destination needed: {job.title}",
                message=result.get("error") or "One browser navigation step requires your input.",
                data={
                    "job_id": job.id,
                    "application_id": app.id,
                    "reason": reason_value,
                    "handoff_public_id": result.get("handoff_public_id"),
                    "stage": "application_target_resolution",
                },
            ))
            db.commit()
            return {"terminal_result": result}

        error = result.get("error") or "Application target resolution failed."
        record_target_failure(
            db,
            app,
            error=error,
            metadata={"source_listing_url": source_url},
        )
        app.status = ApplicationStatus.pending
        current_state = normalize_state(app.automation_state)
        if current_state != ApplicationAutomationState.failed.value:
            transition_application_state(
                db,
                app,
                ApplicationAutomationState.failed,
                "application_target_resolution_failed",
                {"error": error[:500]},
            )
        db.commit()
        return {"terminal_result": result}
    finally:
        db.close()


def install_application_target_task_integration() -> None:
    """Install target resolution ahead of the existing application task body."""
    global _INSTALLED, _ORIGINAL_RUN, _ORIGINAL_ENSURE_APPLICATION_METHOD
    if _INSTALLED:
        return

    from app.tasks import applications as application_tasks

    task = application_tasks.submit_application_task
    _ORIGINAL_RUN = task.run
    _ORIGINAL_ENSURE_APPLICATION_METHOD = application_tasks._ensure_application_method

    def target_aware_application_method(job: Job) -> Dict[str, Any]:
        target_url = _ACTIVE_APPLICATION_TARGET.get()
        if target_url:
            return {
                **dict(job.raw_data or {}),
                "application_method": "external_url",
                "selected_apply_url": target_url,
                "reason": "Using durable application-level employer target",
                "target_resolution_source": "application_record",
            }

        original_url = job.url
        try:
            return _ORIGINAL_ENSURE_APPLICATION_METHOD(job)
        finally:
            # The discovery URL is immutable. Older resolution code may assign an
            # employer URL to Job.url, so restore it before the transaction commits.
            job.url = original_url

    def wrapped_run(application_id: int, dry_run: bool = True, **kwargs):
        prepared = _prepare_target(application_tasks, application_id)
        terminal_result = prepared.get("terminal_result")
        if terminal_result is not None:
            return terminal_result

        target_url = prepared.get("target_url")
        token = _ACTIVE_APPLICATION_TARGET.set(target_url)
        try:
            return _ORIGINAL_RUN(
                application_id,
                dry_run=dry_run,
                **kwargs,
            )
        finally:
            _ACTIVE_APPLICATION_TARGET.reset(token)

    application_tasks._ensure_application_method = target_aware_application_method
    task.run = wrapped_run
    _INSTALLED = True