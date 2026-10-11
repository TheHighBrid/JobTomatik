"""JT5 worker: execute a reserved attempt without approval or pilot gates.

This task is intentionally separate from submit_application_task so the
supervised_submission_integration wrapper never runs.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationStatus,
)
from app.models.job import Job
from app.models.submission_integrity import SubmissionAttempt
from app.models.user import User
from app.services.application_attempt_lifecycle_jt5 import (
    claim_jt5_attempt,
    complete_jt5_attempt,
)
from app.services.application_integrity import submission_is_closed
from app.services.application_state import transition_application_state
from app.services.form_filler import fill_and_submit_application
from app.tasks.applications import (
    _profile_dict,
    _record_result_evidence,
    _run_async,
)

logger = logging.getLogger(__name__)


def _classify_browser_result(result: Dict[str, Any]) -> str:
    """Map browser result to JT5 outcome. Never promote weak evidence to confirmed."""
    if not isinstance(result, dict):
        return "submission_uncertain"
    if result.get("requires_manual_review"):
        log_actions = " ".join(
            str(item.get("action", "")) for item in (result.get("log") or [])
        ).lower()
        if any(
            token in log_actions
            for token in ("submit clicked", "submit_clicked", "final_action")
        ):
            return "submission_uncertain"
        if result.get("submitted_at") or result.get("submission_confirmed"):
            return "submission_uncertain"
        return "failed_pre_submit"
    if result.get("success") and (
        result.get("submitted_at")
        or result.get("submission_confirmed")
        or any(
            bool(item.get("is_sufficient"))
            for item in (result.get("confirmation_evidence") or [])
            if isinstance(item, dict)
        )
    ):
        return "confirmed"
    if result.get("success") and result.get("dry_run"):
        return "failed_pre_submit"
    if result.get("error") and not result.get("submitted_at"):
        return "failed_pre_submit"
    return "submission_uncertain"


@celery_app.task(
    bind=True,
    name="app.tasks.jt5_execution.execute_reserved_application",
    queue="applications",
    max_retries=0,
)
def execute_reserved_application(self, application_id: int, attempt_reference: str):
    db = SessionLocal()
    try:
        attempt = claim_jt5_attempt(db, application_id, attempt_reference)
        if attempt is None:
            db.rollback()
            return {
                "success": False,
                "application_id": application_id,
                "attempt_reference": attempt_reference,
                "error": "attempt_not_claimable",
                "automatic_retry_allowed": False,
            }

        application = (
            db.query(Application)
            .filter(Application.id == application_id)
            .with_for_update()
            .first()
        )
        job = db.query(Job).filter(Job.id == application.job_id).first() if application else None
        user = db.query(User).filter(User.id == application.user_id).first() if application else None
        if not application or not job or not user:
            complete_jt5_attempt(
                db,
                attempt,
                outcome="failed_pre_submit",
                details={"reason": "missing_application_job_or_user"},
            )
            db.commit()
            return {
                "success": False,
                "application_id": application_id,
                "error": "missing_application_job_or_user",
                "automatic_retry_allowed": False,
            }

        # Stale queue message after user/employer already closed the row.
        if submission_is_closed(application):
            complete_jt5_attempt(
                db,
                attempt,
                outcome="confirmed",
                details={
                    "reason": "already_submitted",
                    "idempotent": True,
                    "status": str(
                        getattr(application.status, "value", application.status) or ""
                    ),
                    "state": str(
                        getattr(
                            application.automation_state,
                            "value",
                            application.automation_state,
                        )
                        or ""
                    ),
                },
            )
            db.commit()
            return {
                "success": True,
                "idempotent": True,
                "already_submitted": True,
                "application_id": application_id,
                "attempt_reference": attempt_reference,
                "outcome": "confirmed",
                "automatic_retry_allowed": False,
                "execution_contract": "jt5",
            }

        transition_application_state(
            db,
            application,
            ApplicationAutomationState.applying,
            "jt5_attempt_claimed",
            {"attempt_reference": attempt_reference},
        )
        db.commit()

        # Owner-authorized JT5 path: no pilot flag, no approval reference, no
        # ALLOW_REAL_APPLICATION_SUBMIT check. Browser still enforces real-site limits.
        profile = _profile_dict(user, db, job)
        result = _run_async(
            fill_and_submit_application(
                job.url or "",
                profile,
                application.cover_letter or "",
                user.resume_path or "",
                dry_run=False,
            )
        )
        if not isinstance(result, dict):
            result = {"success": False, "error": "non_dict_browser_result"}

        outcome = _classify_browser_result(result)

        application = db.query(Application).filter(Application.id == application_id).first()
        attempt = (
            db.query(SubmissionAttempt)
            .filter(
                SubmissionAttempt.application_id == application_id,
                SubmissionAttempt.reference == attempt_reference,
            )
            .with_for_update()
            .first()
        )
        if application is None or attempt is None:
            return {
                "success": False,
                "error": "application_or_attempt_missing_after_browser",
                "automatic_retry_allowed": False,
            }

        _record_result_evidence(db, application, result)
        application.automation_log = list(result.get("log") or [])

        if outcome == "confirmed":
            application.status = ApplicationStatus.applied
            if application.applied_at is None:
                if result.get("submitted_at"):
                    try:
                        application.applied_at = datetime.fromisoformat(
                            str(result["submitted_at"]).replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                    except Exception:
                        application.applied_at = datetime.utcnow()
                else:
                    application.applied_at = datetime.utcnow()
            transition_application_state(
                db,
                application,
                ApplicationAutomationState.submitted,
                "jt5_submission_observed",
                {"attempt_reference": attempt_reference},
            )
            transition_application_state(
                db,
                application,
                ApplicationAutomationState.confirmed,
                "jt5_submission_confirmed",
                {"attempt_reference": attempt_reference},
            )
        elif outcome == "failed_pre_submit":
            transition_application_state(
                db,
                application,
                ApplicationAutomationState.ready_to_apply,
                "jt5_failed_pre_submit",
                {
                    "attempt_reference": attempt_reference,
                    "error": str(result.get("error") or "")[:500],
                },
            )
        else:
            transition_application_state(
                db,
                application,
                ApplicationAutomationState.submission_uncertain,
                "jt5_submission_uncertain",
                {"attempt_reference": attempt_reference},
            )

        complete_jt5_attempt(
            db,
            attempt,
            outcome=outcome,
            details={
                "success": bool(result.get("success")),
                "error": result.get("error"),
                "fields_filled": result.get("fields_filled"),
            },
        )
        db.commit()
        return {
            "success": outcome == "confirmed",
            "application_id": application_id,
            "attempt_reference": attempt_reference,
            "outcome": outcome,
            "automatic_retry_allowed": False,
            "execution_contract": "jt5",
        }
    except Exception as exc:
        logger.exception("JT5 execute_reserved_application failed")
        try:
            db.rollback()
            attempt = claim_jt5_attempt(db, application_id, attempt_reference)
            if attempt is None:
                attempt = (
                    db.query(SubmissionAttempt)
                    .filter(
                        SubmissionAttempt.application_id == application_id,
                        SubmissionAttempt.reference == attempt_reference,
                    )
                    .with_for_update()
                    .first()
                )
            application = db.query(Application).filter(Application.id == application_id).first()
            if attempt is not None and attempt.status not in {
                "succeeded",
                "failed",
                "uncertain",
                "blocked",
            }:
                complete_jt5_attempt(
                    db,
                    attempt,
                    outcome="submission_uncertain",
                    details={
                        "reason": "worker_exception",
                        "exception": f"{type(exc).__name__}: {str(exc)[:300]}",
                    },
                )
            if application is not None:
                transition_application_state(
                    db,
                    application,
                    ApplicationAutomationState.submission_uncertain,
                    "jt5_worker_exception",
                    {"attempt_reference": attempt_reference},
                )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("JT5 uncertain finalization failed")
        return {
            "success": False,
            "application_id": application_id,
            "attempt_reference": attempt_reference,
            "outcome": "submission_uncertain",
            "automatic_retry_allowed": False,
            "error": f"{type(exc).__name__}: {str(exc)[:300]}",
        }
    finally:
        db.close()
