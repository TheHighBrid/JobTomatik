"""Prepare the retained Lever application and finish one exact authorized submission."""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import Application, ManualReviewReason
from app.models.job import Job
from app.models.user import User
from app.services.operator_assisted_auto_submit import (
    authorization_snapshot,
    auto_submit_retained_lever_application,
    record_authorization_request,
)
from app.services.operator_assisted_handoff_integration import (
    install_operator_assisted_handoff_integration,
    operator_prepare_scope,
)
from app.services.operator_assisted_question_retention import (
    install_operator_assisted_question_retention,
    summarize_operator_question_retention_result,
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
install_operator_assisted_question_retention()


def _run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def _is_final_submit_boundary(result: dict[str, Any]) -> bool:
    final_reason = ManualReviewReason.operator_final_submit_required.value
    return bool(
        result.get("handoff_public_id")
        and any(
            str(item.get("reason_code") or "") == final_reason
            for item in result.get("review_items") or []
            if isinstance(item, dict)
        )
    )


@celery_app.task(
    bind=True,
    name="app.tasks.operator_assisted.prepare_operator_assisted_application_task",
    queue="applications",
)
def prepare_operator_assisted_application_task(
    self,
    application_id: int,
    auto_final_submit: bool = True,
):
    """Fill once; stop for questions/security, otherwise perform one exact final action.

    Browser creation, retained-tab behavior, and question retention remain owned by the
    existing proven preparation path.  The initial authenticated application action is
    frozen to an exact payload/target before browser work.  If the run reaches the
    verified Lever final-submit boundary unchanged, the separate auto-final service may
    click exactly once.  Any question, CAPTCHA, target drift, validation error, or
    uncertain outcome remains a retained/manual boundary with no automatic retry.
    """

    db = SessionLocal()
    authorization = None
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

        if auto_final_submit:
            authorization = authorization_snapshot(
                preflight,
                task_id=str(getattr(getattr(self, "request", None), "id", "") or ""),
            )
            authorization["application_id"] = application.id
            record_authorization_request(db, application, authorization)
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
    except Exception as exc:
        # Preparation is still safe to retry because no final action has been claimed.
        raise self.retry(exc=exc, countdown=30, max_retries=1)

    if not isinstance(result, dict):
        return result

    result = summarize_operator_question_retention_result(dict(result))
    result["operator_assisted"] = True
    result["auto_final_submit_authorized"] = bool(auto_final_submit)
    result["automated_submission_authorized"] = False
    result["final_submit_clicked_by_jobtomatik"] = False

    if not auto_final_submit or not authorization or not _is_final_submit_boundary(result):
        return result

    try:
        final_result = _run_async(
            auto_submit_retained_lever_application(
                application_id,
                str(result["handoff_public_id"]),
                authorization,
            )
        )
    except Exception as exc:
        # Once a final-boundary helper is entered, never ask Celery to replay the job.
        return {
            **result,
            "success": False,
            "requires_manual_review": True,
            "auto_final_submit_blocked_reason": "auto_final_submit_internal_error",
            "error": f"Auto final-submit stopped safely: {type(exc).__name__}: {str(exc)[:300]}",
            "automatic_retry_allowed": False,
        }

    return {
        **result,
        **dict(final_result or {}),
        "operator_assisted": True,
        "auto_final_submit_authorized": True,
        "automatic_retry_allowed": False,
    }


__all__ = ["prepare_operator_assisted_application_task"]
