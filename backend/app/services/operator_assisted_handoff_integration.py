"""Scoped retained-browser integration for operator-assisted final submission.

Normal dry runs are unchanged. Only the dedicated operator-assisted preparation task
activates this context. In that context, a successful dry run that reaches the exact
final-submit boundary is converted into a retained manual handoff. The browser cannot
be claimed until an exact operator-assisted approval bound to that handoff is consumed.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Mapping, Optional

from app.config import get_settings
from app.models.application import ManualReviewReason
from app.models.handoff import HandoffChallengeType
from app.services.operations_policy import disabled_platforms, platform_key_for_url
from app.services.operations_settings import get_operations_settings


_OPERATOR_PREP_TARGET: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "jobtomatik_operator_assisted_prepare_target",
    default=None,
)
_INSTALLED = False
_ORIGINAL_FLOW = None
_ORIGINAL_FILL = None
_ORIGINAL_CLAIM = None
_ORIGINAL_VERIFY_COMPLETION = None
_ORIGINAL_PERFORM_ACTION = None


def current_operator_prepare_target() -> Optional[Dict[str, Any]]:
    value = _OPERATOR_PREP_TARGET.get()
    return dict(value) if isinstance(value, Mapping) else None


@contextmanager
def operator_prepare_scope(target_metadata: Mapping[str, Any]) -> Iterator[None]:
    token = _OPERATOR_PREP_TARGET.set(dict(target_metadata or {}))
    try:
        yield
    finally:
        _OPERATOR_PREP_TARGET.reset(token)


def _dry_run_requested(args, kwargs) -> bool:
    if "dry_run" in kwargs:
        return bool(kwargs["dry_run"])
    if len(args) >= 5:
        return bool(args[4])
    return True


def _challenge_type(session: Any) -> Optional[str]:
    """Read the typed handoff discriminator without breaking legacy test doubles."""
    value = getattr(session, "challenge_type", None)
    return str(value) if value is not None else None


def _operator_final_action_blockers(url: str) -> list[str]:
    """Return current fail-closed blockers for the human-triggered Lever final action."""

    operations = get_operations_settings()
    core = get_settings()
    platform = platform_key_for_url(str(url or ""))
    disabled = disabled_platforms(operations.disabled_platforms)
    blockers: list[str] = []

    if operations.global_kill_switch:
        blockers.append("global_kill_switch_active")
    if platform in disabled or "all" in disabled:
        blockers.append("platform_disabled")
    if operations.autopilot_enabled:
        blockers.append("operator_assisted_requires_autopilot_disabled")
    if bool(core.allow_real_application_submit):
        blockers.append("operator_assisted_requires_global_submit_disabled")
    if bool(core.lever_supervised_pilot_enabled):
        blockers.append("operator_assisted_requires_platform_pilot_disabled")
    return blockers


def _checkpoint_fresh_live_snapshot(
    session: Any,
    *,
    current_url: str,
    current_fingerprint: str,
) -> None:
    """Commit the freshly verified live page before the employer Submit click."""

    from app.database import SessionLocal
    from app.models.application import Application
    from app.models.handoff import ManualHandoffSession
    from app.services.operator_assisted_final_action import (
        checkpoint_operator_final_action_live_snapshot,
    )

    db = SessionLocal()
    try:
        persisted_session = (
            db.query(ManualHandoffSession)
            .filter(
                ManualHandoffSession.public_id == session.public_id,
                ManualHandoffSession.application_id == session.application_id,
                ManualHandoffSession.user_id == session.user_id,
                ManualHandoffSession.challenge_type == HandoffChallengeType.final_submit.value,
            )
            .with_for_update()
            .first()
        )
        application = (
            db.query(Application)
            .filter(
                Application.id == session.application_id,
                Application.user_id == session.user_id,
            )
            .with_for_update()
            .first()
        )
        if persisted_session is None or application is None:
            raise RuntimeError("The retained final-submit records changed before live checkpointing")

        checkpoint_operator_final_action_live_snapshot(
            db,
            application,
            persisted_session,
            user_id=session.user_id,
            current_url=current_url,
            current_fingerprint=current_fingerprint,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    session.current_url = current_url
    session.current_fingerprint = current_fingerprint
    session.handoff_metadata = {
        **dict(getattr(session, "handoff_metadata", None) or {}),
        "operator_submit_live_snapshot_checkpointed": True,
        "operator_submit_pre_submit_url": current_url,
        "operator_submit_pre_submit_fingerprint": current_fingerprint,
        "automatic_retry_allowed": False,
    }


def install_operator_assisted_handoff_integration() -> None:
    """Install an idempotent, context-gated final-submit handoff extension."""

    global _INSTALLED, _ORIGINAL_FLOW, _ORIGINAL_FILL, _ORIGINAL_CLAIM
    global _ORIGINAL_VERIFY_COMPLETION, _ORIGINAL_PERFORM_ACTION
    if _INSTALLED:
        return

    from app.services import browser_handoff
    from app.services import form_filler_handoff as handoff_filler
    from app.services import handoff_integration
    from app.services import handoff_session
    from app.tasks import applications as application_tasks

    final_reason = ManualReviewReason.operator_final_submit_required.value
    handoff_filler._RESUMABLE_REASONS.add(final_reason)
    handoff_integration._RESUMABLE_REASON_VALUES.add(final_reason)
    handoff_session._ALLOWED_REASON_TO_CHALLENGE[final_reason] = (
        HandoffChallengeType.final_submit.value
    )

    _ORIGINAL_FLOW = handoff_filler.run_ats_application_flow

    async def operator_aware_flow(*args, **kwargs):
        flow = await _ORIGINAL_FLOW(*args, **kwargs)
        target = current_operator_prepare_target()
        if not target or not bool(kwargs.get("dry_run", True)):
            return flow
        if flow.success and flow.ready_to_submit and not flow.requires_manual_review:
            flow.requires_manual_review = True
            flow.error = (
                "The application is fully prepared. The exact final Submit action "
                "is reserved for the authenticated owner."
            )
            flow.review_items.append({
                "reason_code": final_reason,
                "summary": (
                    "Review the fully filled application and make the final Submit "
                    "action yourself after exact approval."
                ),
                "details": {
                    "handoff_stage": "operator_final_submit",
                    "fields_filled": int(flow.fields_filled or 0),
                    "steps_completed": int(flow.steps_completed or 0),
                    "submit_clicked": False,
                    "operator_final_click_required": True,
                    "automated_submission_authorized": False,
                    "queue_submission_authorized": False,
                    "target_identity_hash": target.get("identity_hash"),
                },
            })
            flow.step_evidence.append({
                "action": "operator_final_submit_handoff_ready",
                "adapter": flow.adapter_name,
                "adapter_version": flow.adapter_version,
                "fields_filled": int(flow.fields_filled or 0),
                "submit_clicked": False,
                "operator_final_click_required": True,
                "automated_submission_authorized": False,
                "queue_submission_authorized": False,
            })
        return flow

    handoff_filler.run_ats_application_flow = operator_aware_flow

    _ORIGINAL_FILL = application_tasks.fill_and_submit_application

    async def operator_target_aware_fill(*args, **kwargs):
        target = current_operator_prepare_target()
        dry_run = _dry_run_requested(args, kwargs)
        if target and dry_run and "supervised_target" not in kwargs:
            kwargs["supervised_target"] = dict(target)
        result = await _ORIGINAL_FILL(*args, **kwargs)
        if not target or not dry_run or not isinstance(result, dict):
            return result

        final_boundary = any(
            str(item.get("reason_code") or "") == final_reason
            for item in result.get("review_items") or []
        )
        snapshot = dict(result.get("handoff_snapshot") or {})
        if final_boundary and snapshot:
            snapshot_metadata = dict(snapshot.get("metadata") or {})
            snapshot_metadata.update({
                "operator_assisted_final_submit": True,
                "operator_final_click_required": True,
                "automated_submission_authorized": False,
                "queue_submission_authorized": False,
                "operator_target_identity_hash": target.get("identity_hash"),
            })
            snapshot["metadata"] = snapshot_metadata
            result["handoff_snapshot"] = snapshot
        return result

    application_tasks.fill_and_submit_application = operator_target_aware_fill

    _ORIGINAL_CLAIM = handoff_session.claim_handoff_session

    def approval_gated_claim(db, session, *, user_id: int, resume_token: str):
        if _challenge_type(session) == HandoffChallengeType.final_submit.value:
            from app.services.operator_assisted_submission import (
                operator_final_click_authorized,
            )

            if not operator_final_click_authorized(db, session, user_id=user_id):
                raise handoff_session.HandoffSessionConflict(
                    "Exact operator final-click approval is required before the "
                    "retained application can be opened for interaction."
                )
        return _ORIGINAL_CLAIM(
            db,
            session,
            user_id=user_id,
            resume_token=resume_token,
        )

    handoff_session.claim_handoff_session = approval_gated_claim

    _ORIGINAL_PERFORM_ACTION = browser_handoff.perform_handoff_action

    async def operator_locked_action(
        session,
        *,
        action: str,
        x=None,
        y=None,
        text=None,
        key=None,
        delta_x: float = 0,
        delta_y: float = 0,
    ):
        if _challenge_type(session) != HandoffChallengeType.final_submit.value:
            if action == "operator_submit":
                raise browser_handoff.BrowserHandoffError(
                    "Operator-submit is valid only for an approved final-submit handoff."
                )
            return await _ORIGINAL_PERFORM_ACTION(
                session,
                action=action,
                x=x,
                y=y,
                text=text,
                key=key,
                delta_x=delta_x,
                delta_y=delta_y,
            )

        if action != "operator_submit":
            raise browser_handoff.BrowserHandoffError(
                "The approved final-submit handoff is review-only except for the "
                "single explicit Submit action."
            )

        entry_blockers = _operator_final_action_blockers(str(session.current_url or ""))
        if entry_blockers:
            raise browser_handoff.BrowserHandoffError(
                "Operator-assisted final submit is blocked by the current runtime profile: "
                + ", ".join(entry_blockers)
            )

        playwright, _, _, page = await browser_handoff._connect_local_cdp(session)
        try:
            before = await browser_handoff._verify_session_target(page, session)
            browser_handoff._require_verified_session_target(before)
            adapter = await browser_handoff.detect_ats_adapter(page, page.url)
            expected = browser_handoff._session_supervised_target(session)
            expected_adapter = str(expected.get("adapter") or "lever")
            expected_version = str(expected.get("adapter_version") or "")
            if adapter.name != "lever" or expected_adapter != "lever":
                raise browser_handoff.BrowserHandoffError(
                    "Operator-assisted Phase B final submit is certified only for Lever."
                )
            if expected_version and adapter.version != expected_version:
                raise browser_handoff.BrowserHandoffError(
                    "The retained Lever adapter version changed after owner approval."
                )

            surface = await adapter.resolve_surface(page)
            before_url = str(page.url or "")
            before_page_fingerprint = await browser_handoff.page_fingerprint(page)
            before_step_fingerprint = await adapter.step_fingerprint(surface)
            snapshot_blockers = _operator_final_action_blockers(before_url)
            if snapshot_blockers:
                raise browser_handoff.BrowserHandoffError(
                    "Operator-assisted final submit is blocked before live checkpointing: "
                    + ", ".join(snapshot_blockers)
                )

            submit_control = await adapter.find_submit_button(surface)
            if submit_control is None:
                raise browser_handoff.BrowserHandoffError(
                    "The exact final Submit control is no longer available. Re-prepare "
                    "the retained application instead of guessing."
                )
            try:
                visible = await submit_control.is_visible()
                enabled = await submit_control.is_enabled()
            except Exception as exc:
                raise browser_handoff.BrowserHandoffError(
                    "The final Submit control could not be verified safely."
                ) from exc
            if not visible or not enabled:
                raise browser_handoff.BrowserHandoffError(
                    "The final Submit control is not currently visible and enabled."
                )

            validation_errors = await adapter.extract_validation_errors(surface)
            if validation_errors:
                raise browser_handoff.BrowserHandoffError(
                    "The retained Lever form exposes validation errors. Re-prepare and "
                    "review the exact application instead of submitting it."
                )

            try:
                _checkpoint_fresh_live_snapshot(
                    session,
                    current_url=before_url,
                    current_fingerprint=before_page_fingerprint,
                )
            except Exception as exc:
                raise browser_handoff.BrowserHandoffError(
                    "The fresh live pre-submit page could not be durably checkpointed."
                ) from exc

            # The durable checkpoint is now authoritative. Re-read the live page and
            # every consequential gate after that commit and immediately before click.
            latest_url = str(page.url or "")
            latest_page_fingerprint = await browser_handoff.page_fingerprint(page)
            latest_step_fingerprint = await adapter.step_fingerprint(surface)
            if (
                latest_url != before_url
                or latest_page_fingerprint != before_page_fingerprint
                or latest_step_fingerprint != before_step_fingerprint
            ):
                raise browser_handoff.BrowserHandoffError(
                    "The retained Lever page changed after the durable pre-submit checkpoint. "
                    "Automatic retry is forbidden; verify the employer page instead."
                )

            latest_target = await browser_handoff._verify_session_target(page, session)
            browser_handoff._require_verified_session_target(latest_target)
            final_blockers = _operator_final_action_blockers(latest_url)
            if final_blockers:
                raise browser_handoff.BrowserHandoffError(
                    "Operator-assisted final submit is blocked at the final action boundary: "
                    + ", ".join(final_blockers)
                )

            submit_control = await adapter.find_submit_button(surface)
            if submit_control is None:
                raise browser_handoff.BrowserHandoffError(
                    "The exact final Submit control disappeared after checkpointing."
                )
            try:
                visible = await submit_control.is_visible()
                enabled = await submit_control.is_enabled()
            except Exception as exc:
                raise browser_handoff.BrowserHandoffError(
                    "The final Submit control could not be re-verified safely."
                ) from exc
            if not visible or not enabled:
                raise browser_handoff.BrowserHandoffError(
                    "The final Submit control changed after checkpointing."
                )
            validation_errors = await adapter.extract_validation_errors(surface)
            if validation_errors:
                raise browser_handoff.BrowserHandoffError(
                    "The retained Lever form changed after checkpointing and now exposes "
                    "validation errors. Automatic retry is forbidden."
                )

            await submit_control.click()
            await page.wait_for_timeout(900)
            confirmation_items = await adapter.detect_confirmation(
                surface,
                before_url=before_url,
                before_fingerprint=before_step_fingerprint,
            )
            confirmation_evidence = [item.as_dict() for item in confirmation_items]
            submission_confirmed = any(item.is_sufficient for item in confirmation_items)
            after = await browser_handoff._verify_session_target(
                page,
                session,
                allow_same_site_confirmation=submission_confirmed,
            )
            browser_handoff._require_verified_session_target(after)
            fingerprint = await browser_handoff.page_fingerprint(page)
            return {
                "action": action,
                "current_url": page.url,
                "current_fingerprint": fingerprint,
                "pre_submit_url": before_url,
                "pre_submit_fingerprint": before_page_fingerprint,
                "pre_submit_step_fingerprint": before_step_fingerprint,
                "target_verification": after,
                "submission_confirmed": submission_confirmed,
                "confirmation_evidence": confirmation_evidence,
                "confirmation_detector": "lever_adapter_strict",
                "sensitive_value_logged": False,
            }
        finally:
            await browser_handoff._disconnect(playwright)

    browser_handoff.perform_handoff_action = operator_locked_action

    _ORIGINAL_VERIFY_COMPLETION = browser_handoff.verify_browser_handoff_completion

    async def final_submit_confirmation_required(session):
        verification = await _ORIGINAL_VERIFY_COMPLETION(session)
        if _challenge_type(session) != HandoffChallengeType.final_submit.value:
            return verification

        metadata = dict(session.handoff_metadata or {})
        target_verification = dict(verification.evidence.get("target_verification") or {})
        target_verified = bool(target_verification.get("verified"))
        strong_confirmation_observed = bool(
            metadata.get("operator_submit_confirmation_observed") is True
        )
        generic_confirmation = bool(verification.evidence.get("submission_confirmed"))
        confirmation_url_signal = bool(
            verification.evidence.get("confirmation_url_signal")
        )
        live_snapshot_checkpointed = bool(
            metadata.get("operator_submit_live_snapshot_checkpointed") is True
        )
        pre_submit_url = str(metadata.get("operator_submit_pre_submit_url") or "")
        current_url = str(verification.current_url or "")
        provable_confirmation_transition = bool(
            live_snapshot_checkpointed
            and generic_confirmation
            and confirmation_url_signal
            and pre_submit_url
            and current_url
            and current_url != pre_submit_url
        )
        final_confirmed = bool(
            target_verified
            and (strong_confirmation_observed or provable_confirmation_transition)
        )
        verification.challenge_cleared = final_confirmed
        verification.evidence["submission_confirmed"] = final_confirmed
        verification.evidence["operator_submit_confirmation_observed"] = (
            strong_confirmation_observed
        )
        verification.evidence["operator_submit_live_snapshot_checkpointed"] = (
            live_snapshot_checkpointed
        )
        verification.evidence["provable_confirmation_transition"] = (
            provable_confirmation_transition
        )
        verification.evidence["verification_method"] = (
            "operator_final_submit_strict_confirmation"
            if final_confirmed
            else "operator_final_submit_confirmation_required"
        )
        return verification

    browser_handoff.verify_browser_handoff_completion = final_submit_confirmation_required

    # HTTP routers imported these function objects before this compatibility layer is
    # installed. Replace those local references too so API calls share the same gates.
    try:
        from app.api import handoffs as handoff_api

        handoff_api.claim_handoff_session = approval_gated_claim
        handoff_api.perform_handoff_action = operator_locked_action
        handoff_api.verify_browser_handoff_completion = final_submit_confirmation_required
    except Exception:
        # Worker-only imports do not need the HTTP router patch.
        pass

    _INSTALLED = True


__all__ = [
    "current_operator_prepare_target",
    "install_operator_assisted_handoff_integration",
    "operator_prepare_scope",
]
