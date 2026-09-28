"""One-shot Lever final submission layered on the proven retained-browser path.

This module deliberately does not create, navigate, or recover browser tabs.  It only
acts after the existing operator-assisted preparation flow has already retained the
exact Lever final-submit handoff.  Unknown questions and security challenges remain
handoff boundaries.  A final click is attempted once, only after a fresh read-only
precheck proves the exact target, validation state, submit control, and hCaptcha state.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from app.database import SessionLocal
from app.models.application import (
    Application,
    ApplicationAutomationState,
    ApplicationEvent,
    ApplicationStatus,
    ManualReviewTask,
    SubmissionEvidenceType,
)
from app.models.handoff import (
    ACTIVE_HANDOFF_STATUSES,
    HandoffChallengeType,
    HandoffSessionStatus,
    ManualHandoffSession,
)
from app.models.job import Job
from app.models.submission_approval import SubmissionApproval
from app.models.user import User
from app.services import browser_handoff as browser_handoff_service
from app.services.application_state import (
    has_sufficient_submission_evidence,
    normalize_state,
    record_submission_evidence,
    resolve_manual_review_task,
    transition_application_state,
)
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


_AUTH_FIELDS = (
    "employer",
    "role",
    "application_url",
    "combined_payload_hash",
    "target_identity_hash",
)


def authorization_snapshot(preflight: Mapping[str, Any], *, task_id: str = "") -> dict[str, Any]:
    """Freeze the exact payload/target authorized by the user's initial Apply action."""

    return {
        "application_id": preflight.get("application_id"),
        "task_id": str(task_id or ""),
        "requested_at": datetime.utcnow().isoformat(),
        "authorization_source": "authenticated_operator_prepare_request",
        **{field: preflight.get(field) for field in _AUTH_FIELDS},
    }


def record_authorization_request(db, application: Application, snapshot: Mapping[str, Any]) -> None:
    db.add(
        ApplicationEvent(
            application_id=application.id,
            event_type="operator_assisted_auto_final_submit_authorized",
            from_state=application.automation_state,
            to_state=application.automation_state,
            payload={
                **dict(snapshot),
                "one_exact_final_action": True,
                "automatic_retry_allowed": False,
            },
        )
    )


def _authorization_drift(preflight: Mapping[str, Any], snapshot: Mapping[str, Any]) -> list[str]:
    return [
        field
        for field in _AUTH_FIELDS
        if str(preflight.get(field) or "") != str(snapshot.get(field) or "")
    ]


def _manual_boundary_result(
    *,
    handoff_public_id: str,
    reason: str,
    blocker: str,
) -> dict[str, Any]:
    return {
        "success": False,
        "operator_assisted": True,
        "requires_manual_review": True,
        "handoff_public_id": handoff_public_id,
        "error": reason,
        "auto_final_submit_blocked_reason": blocker,
        "auto_final_submit_authorized": True,
        "final_submit_clicked_by_jobtomatik": False,
        "automatic_retry_allowed": False,
    }


async def _precheck_retained_lever_page(session: ManualHandoffSession) -> dict[str, Any]:
    """Read-only gate before any approval is consumed or final action is claimed."""

    playwright = None
    try:
        playwright, _, _, page = await browser_handoff_service._connect_local_cdp(session)
        from app.services.operator_assisted_live_pilot_hardening import (
            passive_verification_requires_manual_browser,
            passive_verification_state,
        )

        verification_state = await passive_verification_state(page)
        if passive_verification_requires_manual_browser(verification_state):
            return {
                "ready": False,
                "blocker": "captcha_or_passive_verification",
                "reason": (
                    "Lever requires human verification. The retained Chrome tab was preserved; "
                    "JobTomatik did not click Submit."
                ),
            }

        target = await browser_handoff_service._verify_session_target(page, session)
        browser_handoff_service._require_verified_session_target(target)
        adapter = await browser_handoff_service.detect_ats_adapter(page, page.url)
        expected = browser_handoff_service._session_supervised_target(session)
        expected_adapter = str(expected.get("adapter") or "lever")
        expected_version = str(expected.get("adapter_version") or "")
        if adapter.name != "lever" or expected_adapter != "lever":
            return {
                "ready": False,
                "blocker": "target_not_lever",
                "reason": "The retained page is no longer the exact approved Lever target.",
            }
        if expected_version and adapter.version != expected_version:
            return {
                "ready": False,
                "blocker": "adapter_version_drift",
                "reason": "The retained Lever adapter version changed after preparation.",
            }

        surface = await adapter.resolve_surface(page)
        validation_errors = await adapter.extract_validation_errors(surface)
        if validation_errors:
            return {
                "ready": False,
                "blocker": "validation_errors",
                "reason": "The retained Lever form still exposes validation errors.",
            }

        submit_control = await adapter.find_submit_button(surface)
        if submit_control is None:
            return {
                "ready": False,
                "blocker": "submit_control_missing",
                "reason": "The exact final Lever Submit control is not available.",
            }
        try:
            visible = await submit_control.is_visible()
            enabled = await submit_control.is_enabled()
        except Exception:
            visible = False
            enabled = False
        if not visible or not enabled:
            return {
                "ready": False,
                "blocker": "submit_control_not_ready",
                "reason": "The exact final Lever Submit control is not visible and enabled.",
            }

        return {
            "ready": True,
            "current_url": str(page.url or ""),
            "target_verification": target,
        }
    finally:
        if playwright is not None:
            await browser_handoff_service._disconnect(playwright)


async def _capture_confirmation_screenshot(session: ManualHandoffSession) -> str | None:
    playwright = None
    try:
        playwright, _, _, page = await browser_handoff_service._connect_local_cdp(session)
        verification = await browser_handoff_service._verify_session_target(
            page,
            session,
            allow_same_site_confirmation=True,
        )
        browser_handoff_service._require_verified_session_target(verification)
        evidence_dir = (
            Path(__file__).resolve().parents[2]
            / ".runtime"
            / "submission-evidence"
            / f"application-{session.application_id}"
        )
        evidence_dir.mkdir(parents=True, exist_ok=True)
        path = evidence_dir / f"lever-confirmation-{session.public_id}.png"
        await page.screenshot(path=str(path), type="png", full_page=False)
        return str(path)
    except Exception:
        return None
    finally:
        if playwright is not None:
            await browser_handoff_service._disconnect(playwright)


def _record_confirmation_evidence(
    db,
    application: Application,
    result: Mapping[str, Any],
    *,
    screenshot_path: str | None,
) -> None:
    evidence = result.get("confirmation_evidence") or []
    if isinstance(evidence, Mapping):
        evidence = [evidence]
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        record_submission_evidence(
            db,
            application,
            item.get("evidence_type", SubmissionEvidenceType.success_banner.value),
            is_sufficient=bool(item.get("is_sufficient", False)),
            final_url=item.get("final_url") or result.get("current_url"),
            confirmation_text=item.get("confirmation_text"),
            selector=item.get("selector"),
            external_application_id=item.get("external_application_id"),
            screenshot_path=item.get("screenshot_path"),
            html_snapshot_path=item.get("html_snapshot_path"),
            payload_hash=item.get("payload_hash"),
            metadata=item.get("metadata") or {},
        )

    if screenshot_path:
        record_submission_evidence(
            db,
            application,
            SubmissionEvidenceType.screenshot,
            is_sufficient=False,
            final_url=str(result.get("current_url") or ""),
            screenshot_path=screenshot_path,
            metadata={
                "capture_stage": "post_submit_confirmation",
                "handoff_public_id": result.get("handoff_public_id"),
            },
        )


def _mark_confirmed(
    db,
    application: Application,
    session: ManualHandoffSession,
    result: Mapping[str, Any],
) -> None:
    review = db.query(ManualReviewTask).filter(
        ManualReviewTask.id == session.manual_review_id
    ).first()
    if review is not None:
        resolve_manual_review_task(
            db,
            application,
            review,
            "Lever employer confirmation detected after JobTomatik's authorized one-shot final action.",
        )

    state = normalize_state(application.automation_state)
    if state == ApplicationAutomationState.ready_to_apply.value:
        transition_application_state(
            db,
            application,
            ApplicationAutomationState.applying,
            "operator_assisted_auto_final_action_reconciled",
            {"handoff_public_id": session.public_id},
        )

    application.status = ApplicationStatus.applied
    application.applied_at = application.applied_at or datetime.utcnow()
    transition_application_state(
        db,
        application,
        ApplicationAutomationState.submitted,
        "operator_assisted_auto_submission_confirmation_detected",
        {
            "handoff_public_id": session.public_id,
            "final_url": result.get("current_url"),
            "confirmation_detector": result.get("confirmation_detector"),
        },
    )
    transition_application_state(
        db,
        application,
        ApplicationAutomationState.confirmed,
        "operator_assisted_auto_submission_confirmed",
        {
            "handoff_public_id": session.public_id,
            "evidence_count": len(result.get("confirmation_evidence") or []),
        },
    )
    session.status = HandoffSessionStatus.completed.value
    session.completed_at = session.completed_at or datetime.utcnow()
    session.failure_reason = None
    session.lock_version = (session.lock_version or 0) + 1

    note = (
        f"[{datetime.utcnow().isoformat()}] JobTomatik confirmed Lever submission "
        f"via {result.get('confirmation_detector') or 'employer confirmation'}; "
        f"final URL: {result.get('current_url') or session.current_url or ''}."
    )
    application.notes = f"{application.notes.rstrip()}\n{note}" if application.notes else note


def _load_records(db, application_id: int, handoff_public_id: str):
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
        ManualHandoffSession.status.in_(ACTIVE_HANDOFF_STATUSES),
    ).first()
    if not user or not job:
        raise OperatorAssistedSubmissionError("Application user or job is missing")
    if session is None:
        raise OperatorAssistedSubmissionError("Retained final-submit handoff not found")
    return application, user, job, session


async def auto_submit_retained_lever_application(
    application_id: int,
    handoff_public_id: str,
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    """Perform one authorized Lever final click without touching browser creation logic."""

    db = SessionLocal()
    try:
        application, user, job, session = _load_records(db, application_id, handoff_public_id)
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
        drift = _authorization_drift(preflight, authorization)
        if drift:
            db.add(ApplicationEvent(
                application_id=application.id,
                event_type="operator_assisted_auto_final_submit_blocked",
                from_state=application.automation_state,
                to_state=application.automation_state,
                payload={"reason": "authorization_drift", "fields": drift},
            ))
            db.commit()
            return _manual_boundary_result(
                handoff_public_id=handoff_public_id,
                blocker="authorization_drift",
                reason="The exact application payload or target changed after authorization.",
            )
        db.commit()
    finally:
        db.close()

    precheck = await _precheck_retained_lever_page(session)
    if not precheck.get("ready"):
        return _manual_boundary_result(
            handoff_public_id=handoff_public_id,
            blocker=str(precheck.get("blocker") or "precheck_blocked"),
            reason=str(precheck.get("reason") or "The retained final action requires review."),
        )

    db = SessionLocal()
    try:
        application, user, job, session = _load_records(db, application_id, handoff_public_id)
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
        drift = _authorization_drift(preflight, authorization)
        if drift:
            db.rollback()
            return _manual_boundary_result(
                handoff_public_id=handoff_public_id,
                blocker="authorization_drift",
                reason="The exact application changed after the final precheck.",
            )

        approval = issue_operator_assisted_approval(
            db,
            application,
            user,
            job,
            handoff_public_id=handoff_public_id,
            confirm_employer=str(authorization.get("employer") or ""),
            confirm_role=str(authorization.get("role") or ""),
            confirm_application_url=str(authorization.get("application_url") or ""),
            confirm_operator_final_click=True,
            expires_in_minutes=5,
            notes="One-shot final action authorized by the authenticated initial Apply request.",
            target_metadata=target_metadata,
        )
        approval.approval_metadata = {
            **dict(approval.approval_metadata or {}),
            "auto_final_submit_authorized": True,
            "authorization_source": authorization.get("authorization_source"),
            "authorization_task_id": authorization.get("task_id"),
            "authorization_requested_at": authorization.get("requested_at"),
            "automatic_retry_allowed": False,
        }
        validate_operator_assisted_approval(
            db,
            application,
            user,
            job,
            reference=approval.reference,
            consume=True,
            target_metadata=target_metadata,
        )
        approval_reference = approval.reference
        db.commit()
    except Exception as exc:
        db.rollback()
        return _manual_boundary_result(
            handoff_public_id=handoff_public_id,
            blocker="approval_claim_blocked",
            reason=str(exc),
        )
    finally:
        db.close()

    db = SessionLocal()
    try:
        application, _, _, session = _load_records(db, application_id, handoff_public_id)
        approval = claim_operator_final_action(
            db,
            application,
            session,
            user_id=application.user_id,
        )
        approval_reference = approval.reference
        db.commit()
    except Exception as exc:
        db.rollback()
        return _manual_boundary_result(
            handoff_public_id=handoff_public_id,
            blocker="final_action_claim_blocked",
            reason=str(exc),
        )
    finally:
        db.close()

    try:
        result = await browser_handoff_service.perform_handoff_action(
            session,
            action="operator_submit",
        )
    except Exception as exc:
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
                finalize_operator_final_action(
                    db,
                    application,
                    persisted_session,
                    approval,
                    error=exc,
                )
                db.add(ApplicationEvent(
                    application_id=application.id,
                    event_type="operator_assisted_auto_final_submit_uncertain",
                    from_state=application.automation_state,
                    to_state=application.automation_state,
                    payload={
                        "handoff_public_id": handoff_public_id,
                        "approval_reference": approval_reference,
                        "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                        "automatic_retry_allowed": False,
                    },
                ))
                db.commit()
        finally:
            db.close()
        return {
            **_manual_boundary_result(
                handoff_public_id=handoff_public_id,
                blocker="final_action_outcome_uncertain",
                reason=(
                    "The one-shot final action became uncertain. Automatic retry is disabled; "
                    "verify the retained employer page instead."
                ),
            ),
            "approval_reference": approval_reference,
            "final_action_started": True,
        }

    result = dict(result or {})
    result["handoff_public_id"] = handoff_public_id
    screenshot_path = None
    if bool(result.get("submission_confirmed")):
        screenshot_path = await _capture_confirmation_screenshot(session)

    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).first()
        persisted_session = db.query(ManualHandoffSession).filter(
            ManualHandoffSession.public_id == handoff_public_id
        ).first()
        approval = db.query(SubmissionApproval).filter(
            SubmissionApproval.reference == approval_reference
        ).first()
        if not application or not persisted_session or not approval:
            raise OperatorAssistedSubmissionError("Final action records disappeared during reconciliation")

        persisted_session.current_url = str(result.get("current_url") or persisted_session.current_url or "")
        persisted_session.current_fingerprint = str(
            result.get("current_fingerprint") or persisted_session.current_fingerprint or ""
        )
        finalize_operator_final_action(
            db,
            application,
            persisted_session,
            approval,
            result=result,
        )
        _record_confirmation_evidence(
            db,
            application,
            result,
            screenshot_path=screenshot_path,
        )
        db.flush()

        confirmed = bool(result.get("submission_confirmed")) and has_sufficient_submission_evidence(
            db, application.id
        )
        if confirmed:
            _mark_confirmed(db, application, persisted_session, result)
        else:
            db.add(ApplicationEvent(
                application_id=application.id,
                event_type="operator_assisted_auto_final_submit_awaiting_confirmation",
                from_state=application.automation_state,
                to_state=application.automation_state,
                payload={
                    "handoff_public_id": handoff_public_id,
                    "approval_reference": approval_reference,
                    "automatic_retry_allowed": False,
                },
            ))
        db.commit()
    except Exception as exc:
        db.rollback()
        return {
            **_manual_boundary_result(
                handoff_public_id=handoff_public_id,
                blocker="confirmation_reconciliation_failed",
                reason=str(exc),
            ),
            "approval_reference": approval_reference,
            "final_action_started": True,
        }
    finally:
        db.close()

    return {
        **result,
        "success": bool(result.get("submission_confirmed")),
        "operator_assisted": True,
        "auto_final_submit_authorized": True,
        "approval_reference": approval_reference,
        "final_submit_clicked_by_jobtomatik": True,
        "confirmation_screenshot_path": screenshot_path,
        "automatic_retry_allowed": False,
    }


__all__ = [
    "authorization_snapshot",
    "auto_submit_retained_lever_application",
    "record_authorization_request",
]
