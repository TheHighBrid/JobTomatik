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


_SUBMIT_LOG_ACTIONS = frozenset({
    "ats_submit_clicked",
    "submit clicked",
    "submit_clicked",
    "final_submit",
})

_PRE_BROWSER_ERRORS = frozenset({
    "invalid or unsupported job url",
    "placeholder url; manual application required",
    "playwright not installed",
})


def _log_actions(result: Dict[str, Any]) -> set[str]:
    actions: set[str] = set()
    for item in result.get("log") or []:
        if isinstance(item, dict):
            action = str(item.get("action") or "").strip().lower()
            if action:
                actions.add(action)
    return actions


def normalize_jt5_browser_result(result: Any) -> Dict[str, Any]:
    """Map form_filler / ATS flow outputs onto the JT5 evidence contract.

    Never invent confirmation. Only mark pre_submit_failure_verified when the
    failure is provably before any final-submit attempt.
    """
    if not isinstance(result, dict):
        return {
            "success": False,
            "error": "non_dict_browser_result",
            "final_submit_attempted": None,
            "pre_submit_failure_verified": False,
        }

    normalized = dict(result)
    actions = _log_actions(normalized)
    submit_clicked = bool(normalized.get("submit_clicked"))
    submit_from_log = bool(actions & _SUBMIT_LOG_ACTIONS)

    if "final_submit_attempted" not in normalized or normalized.get("final_submit_attempted") is None:
        if submit_clicked or submit_from_log:
            normalized["final_submit_attempted"] = True
        elif normalized.get("submit_clicked") is False and not submit_from_log:
            normalized["final_submit_attempted"] = False
        else:
            # No explicit signal: treat as unknown until other evidence appears.
            if not actions and not normalized.get("ats_adapter"):
                normalized["final_submit_attempted"] = False
            else:
                normalized["final_submit_attempted"] = None

    # Conflicting final-action evidence invalidates pre-submit proof.
    if normalized.get("pre_submit_failure_verified") is True:
        if submit_clicked or submit_from_log or normalized.get("final_submit_attempted") is not False:
            normalized["pre_submit_failure_verified"] = False
        return normalized

    error_text = str(normalized.get("error") or "").strip().lower()
    pre_browser = error_text in _PRE_BROWSER_ERRORS
    browser_started = "navigate" in actions or bool(normalized.get("ats_adapter"))
    if (
        normalized.get("success") is False
        and normalized.get("final_submit_attempted") is False
        and not submit_from_log
        and pre_browser
        and not browser_started
    ):
        normalized["pre_submit_failure_verified"] = True
    else:
        normalized.setdefault("pre_submit_failure_verified", False)
    return normalized


def _classify_browser_result(result: Dict[str, Any]) -> str:
    """Fail closed unless durable confirmation or explicit pre-submit proof exists.

    A missing timestamp or an error message alone cannot establish that the
    employer never received the final action.
    """
    normalized = normalize_jt5_browser_result(result)
    if not isinstance(normalized, dict):
        return "submission_uncertain"
    evidence = normalized.get("confirmation_evidence") or []
    if isinstance(evidence, dict):
        evidence = [evidence]
    if normalized.get("success") and any(
        isinstance(item, dict) and bool(item.get("is_sufficient"))
        for item in evidence
    ):
        return "confirmed"
    if (
        normalized.get("success") is False
        and normalized.get("final_submit_attempted") is False
        and normalized.get("pre_submit_failure_verified") is True
    ):
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

        result = normalize_jt5_browser_result(result)
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


@celery_app.task(
    name="app.tasks.jt5_execution.reconcile_stale_reserved_applications",
    queue="applications",
    max_retries=0,
)
def reconcile_stale_reserved_applications():
    """Sweep stale JT5 reservations without triggering browser execution."""
    from app.services.jt5_reconciliation import reconcile_stale_jt5_attempts

    db = SessionLocal()
    try:
        references = reconcile_stale_jt5_attempts(db)
        return {"reconciled": len(references), "attempt_references": references}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
