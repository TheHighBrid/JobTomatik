"""Execute the already-prepared Lever final action once.

This module deliberately does not create, navigate, reconnect, or replace browser
sessions. It assumes the existing operator-assisted preparation flow has already
retained the exact Lever final-submit handoff and reuses the current once-only
operator_submit safety path.

Outcome contract (never a second click):
* confirmed (strict Lever adapter check, or bounded read-only re-check of the
  retained page) -> returned for reconciliation to applied/confirmed;
* Submit possibly clicked but unconfirmed -> ``final_submit_click_possible`` with
  the observed URL/fingerprint so the caller records ``submission_uncertain``;
* fail closed before the click (control missing/hidden/disabled, validation
  errors, hCaptcha, gate drift) -> ``final_submit_click_possible`` is False;
* already applied / uncertain / previously checkpointed -> refused up front.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.database import SessionLocal
from app.models.application import Application, ApplicationAutomationState
from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.user import User
from app.services import browser_handoff as browser_handoff_service
from app.services.application_integrity import submission_is_closed
from app.services.application_state import normalize_state
from app.services.operator_assisted_final_action import (
    claim_operator_final_action,
    finalize_operator_final_action,
)
from app.services.operator_assisted_submission import (
    OperatorAssistedSubmissionError,
    build_operator_assisted_preflight,
    issue_operator_assisted_approval,
    validate_operator_assisted_approval,
)
from app.services.supervised_target_identity import (
    persist_supervised_target_metadata,
    resolve_supervised_target_metadata,
)


def _load(db, application_id: int, handoff_public_id: str):
    application = db.query(Application).filter(Application.id == application_id).first()
    if application is None:
        raise OperatorAssistedSubmissionError("Application not found")
    user = db.query(User).filter(User.id == application.user_id).first()
    job = db.query(Job).filter(Job.id == application.job_id).first()
    session = db.query(ManualHandoffSession).filter(
        ManualHandoffSession.public_id == handoff_public_id,
        ManualHandoffSession.application_id == application.id,
        ManualHandoffSession.user_id == application.user_id,
        ManualHandoffSession.challenge_type == HandoffChallengeType.final_submit.value,
    ).first()
    if user is None or job is None:
        raise OperatorAssistedSubmissionError("Application user or job is missing")
    if session is None:
        raise OperatorAssistedSubmissionError("Retained final-submit handoff not found")
    return application, user, job, session


def _blocked(handoff_public_id: str, reason: str) -> dict[str, Any]:
    return {
        "success": False,
        "requires_manual_review": True,
        "handoff_public_id": handoff_public_id,
        "error": reason,
        "final_submit_clicked_by_jobtomatik": False,
        "automatic_retry_allowed": False,
    }


# Lever posts the form and then redirects to ``/thanks``. The strict adapter check in
# the click boundary runs once shortly after the click; these bounded, read-only
# re-checks reuse the retained-handoff confirmation verifier (the same one used for
# owner-completed submissions) so a slow redirect is not misreported as unconfirmed.
CONFIRMATION_RECHECK_ATTEMPTS = 4
CONFIRMATION_RECHECK_INTERVAL_SECONDS = 2.5
PASSIVE_CONFIRMATION_DETECTOR = "retained_operator_completion_verifier"


def _prior_final_click_possible(db, application_id: int) -> bool:
    """True when any earlier final action for this application may have clicked Submit.

    The click boundary durably checkpoints the live page *before* touching the
    employer Submit control, so an approval without that checkpoint provably never
    clicked. Anything checkpointed or observed is treated as a possible submission.
    """

    approvals = (
        db.query(SubmissionApproval)
        .filter(SubmissionApproval.application_id == application_id)
        .all()
    )
    for approval in approvals:
        metadata = dict(approval.approval_metadata or {})
        if (
            metadata.get("operator_submit_live_snapshot_checkpointed") is True
            or metadata.get("operator_submit_confirmation_observed") is True
        ):
            return True
    return False


def _automatic_final_submit_guard(db, application: Application) -> str:
    """Return a reason when an automatic final click would be a resubmission."""

    if submission_is_closed(application):
        return "application_already_submitted"
    if normalize_state(application.automation_state) == (
        ApplicationAutomationState.submission_uncertain.value
    ):
        return "previous_submission_outcome_uncertain"
    if _prior_final_click_possible(db, application.id):
        return "final_submit_already_attempted"
    return ""


def _load_handoff(handoff_public_id: str) -> Optional[ManualHandoffSession]:
    db = SessionLocal()
    try:
        return db.query(ManualHandoffSession).filter(
            ManualHandoffSession.public_id == handoff_public_id
        ).first()
    finally:
        db.close()


def _live_snapshot_checkpointed(session: Optional[ManualHandoffSession]) -> bool:
    metadata = dict(getattr(session, "handoff_metadata", None) or {})
    return metadata.get("operator_submit_live_snapshot_checkpointed") is True


async def _passive_confirmation(handoff_public_id: str) -> dict[str, Any]:
    """Re-read the retained page for employer confirmation without interacting."""

    last_error = ""
    for attempt in range(CONFIRMATION_RECHECK_ATTEMPTS):
        if attempt:
            await asyncio.sleep(CONFIRMATION_RECHECK_INTERVAL_SECONDS)
        session = _load_handoff(handoff_public_id)
        if session is None:
            return {"confirmed": False, "error": "handoff_missing"}
        try:
            verification = await browser_handoff_service.verify_browser_handoff_completion(
                session
            )
        except Exception as exc:  # the page may still be navigating
            last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            continue
        evidence = dict(verification.evidence or {})
        if verification.challenge_cleared and bool(evidence.get("submission_confirmed")):
            return {
                "confirmed": True,
                "attempts": attempt + 1,
                "current_url": verification.current_url,
                "current_fingerprint": verification.current_fingerprint,
                "confirmation_evidence": list(evidence.get("confirmation_evidence") or []),
                "target_verification": dict(evidence.get("target_verification") or {}),
                "verification_method": evidence.get("verification_method"),
            }
        last_error = str(evidence.get("verification_method") or "confirmation_not_observed")
    return {
        "confirmed": False,
        "attempts": CONFIRMATION_RECHECK_ATTEMPTS,
        "error": last_error or "confirmation_not_observed",
    }


def _merge_passive_confirmation(result: dict[str, Any], passive: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "submission_confirmed": True,
        "current_url": passive.get("current_url") or result.get("current_url"),
        "current_fingerprint": passive.get("current_fingerprint")
        or result.get("current_fingerprint"),
        "confirmation_evidence": passive.get("confirmation_evidence") or [],
        "target_verification": passive.get("target_verification")
        or result.get("target_verification"),
        "confirmation_detector": PASSIVE_CONFIRMATION_DETECTOR,
        "passive_confirmation_attempts": passive.get("attempts"),
        "passive_confirmation_method": passive.get("verification_method"),
    }


def _finalize(
    handoff_public_id: str,
    application_id: int,
    approval_reference: str,
    *,
    require: bool = False,
    **kwargs,
) -> None:
    """Persist the observed outcome through the existing once-only final-action ledger."""

    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).first()
        persisted_session = db.query(ManualHandoffSession).filter(
            ManualHandoffSession.public_id == handoff_public_id
        ).first()
        approval = db.query(SubmissionApproval).filter(
            SubmissionApproval.reference == approval_reference
        ).first()
        if application and persisted_session and approval:
            result = kwargs.get("result")
            if result is not None:
                persisted_session.current_url = str(
                    result.get("current_url") or persisted_session.current_url or ""
                )
                persisted_session.current_fingerprint = str(
                    result.get("current_fingerprint")
                    or persisted_session.current_fingerprint
                    or ""
                )
            finalize_operator_final_action(
                db,
                application,
                persisted_session,
                approval,
                **kwargs,
            )
            db.commit()
        elif require:
            raise OperatorAssistedSubmissionError(
                "Final-submit records disappeared during reconciliation"
            )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def submit_retained_lever_final_action(
    application_id: int,
    handoff_public_id: str,
) -> dict[str, Any]:
    """Click the retained Lever Submit control once and return its confirmation result."""

    db = SessionLocal()
    approval_reference = ""
    try:
        application, user, job, session = _load(db, application_id, handoff_public_id)
        guard = _automatic_final_submit_guard(db, application)
        if guard:
            return {
                **_blocked(
                    handoff_public_id,
                    "Automatic final submit refused to resubmit: " + guard,
                ),
                "idempotency_guard": guard,
                "final_submit_click_possible": False,
            }
        target_metadata = await resolve_supervised_target_metadata(job)
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
            return _blocked(
                handoff_public_id,
                "Final submit preflight blocked: " + ", ".join(preflight["blockers"]),
            )

        approval = issue_operator_assisted_approval(
            db,
            application,
            user,
            job,
            handoff_public_id=handoff_public_id,
            confirm_employer=preflight["employer"],
            confirm_role=preflight["role"],
            confirm_application_url=preflight["application_url"],
            confirm_operator_final_click=True,
            expires_in_minutes=5,
            notes="Authorized by the authenticated operator-assisted application request.",
            target_metadata=target_metadata,
        )
        validate_operator_assisted_approval(
            db,
            application,
            user,
            job,
            reference=approval.reference,
            consume=True,
            target_metadata=target_metadata,
        )
        # SessionLocal uses autoflush=False. Without this flush the claim below queries
        # the database for the *consumed* approval, still sees it as ``active``, and
        # always refuses ("Consumed exact operator approval is required ..."), so the
        # retained Submit control was never clicked.
        db.flush()
        approval = claim_operator_final_action(
            db,
            application,
            session,
            user_id=application.user_id,
        )
        approval_reference = approval.reference
        db.commit()
        # commit() expires every instance; the browser boundary reads the handoff
        # after this session closes, so load it fully and detach it explicitly.
        db.refresh(session)
        db.expunge(session)
    except Exception as exc:
        db.rollback()
        return _blocked(handoff_public_id, str(exc))
    finally:
        db.close()

    try:
        result = await browser_handoff_service.perform_handoff_action(
            session,
            action="operator_submit",
        )
    except Exception as exc:
        try:
            _finalize(handoff_public_id, application_id, approval_reference, error=exc)
        except Exception:
            pass
        # The click boundary checkpoints the live page durably before touching
        # Submit. Without that checkpoint the control was provably never clicked
        # (missing, hidden, disabled, validation errors, hCaptcha, gate drift ...).
        click_possible = _live_snapshot_checkpointed(_load_handoff(handoff_public_id))
        if click_possible:
            passive = await _passive_confirmation(handoff_public_id)
            if passive.get("confirmed"):
                confirmed = _merge_passive_confirmation(
                    {"action": "operator_submit", "sensitive_value_logged": False},
                    passive,
                )
                try:
                    _finalize(
                        handoff_public_id,
                        application_id,
                        approval_reference,
                        result=confirmed,
                    )
                except Exception:
                    pass
                return {
                    **confirmed,
                    "approval_reference": approval_reference,
                    "handoff_public_id": handoff_public_id,
                    "final_submit_clicked_by_jobtomatik": True,
                    "final_submit_click_possible": True,
                    "automatic_retry_allowed": False,
                }
            return {
                **_blocked(
                    handoff_public_id,
                    "Final submit outcome is uncertain; automatic retry is disabled.",
                ),
                "approval_reference": approval_reference,
                "final_submit_click_possible": True,
                "submission_confirmed": False,
                "action_error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "passive_confirmation": passive,
            }
        return {
            **_blocked(
                handoff_public_id,
                "Final submit was not clicked: " + str(exc)[:300],
            ),
            "approval_reference": approval_reference,
            "final_submit_click_possible": False,
            "submission_confirmed": False,
        }

    result = dict(result or {})
    passive: dict[str, Any] = {}
    if not bool(result.get("submission_confirmed")):
        passive = await _passive_confirmation(handoff_public_id)
        if passive.get("confirmed"):
            result = _merge_passive_confirmation(result, passive)
    try:
        _finalize(
            handoff_public_id,
            application_id,
            approval_reference,
            require=True,
            result=result,
        )
    except Exception as exc:
        return {
            **_blocked(handoff_public_id, str(exc)),
            **{key: value for key, value in result.items() if key != "success"},
            "approval_reference": approval_reference,
            "final_submit_clicked_by_jobtomatik": True,
            "final_submit_click_possible": True,
            "submission_confirmed": False,
            "reconciliation_error": str(exc)[:300],
        }

    return {
        **result,
        "approval_reference": approval_reference,
        "handoff_public_id": handoff_public_id,
        "final_submit_clicked_by_jobtomatik": True,
        "final_submit_click_possible": True,
        "automatic_retry_allowed": False,
        **({"passive_confirmation": passive} if passive and not passive.get("confirmed") else {}),
    }


__all__ = ["submit_retained_lever_final_action"]
