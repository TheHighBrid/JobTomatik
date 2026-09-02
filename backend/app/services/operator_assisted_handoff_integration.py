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

from app.models.application import ManualReviewReason
from app.models.handoff import HandoffChallengeType


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
            })
        return flow

    handoff_filler.run_ats_application_flow = operator_aware_flow

    _ORIGINAL_FILL = application_tasks.fill_and_submit_application

    async def operator_target_aware_fill(*args, **kwargs):
        target = current_operator_prepare_target()
        if target and _dry_run_requested(args, kwargs) and "supervised_target" not in kwargs:
            kwargs["supervised_target"] = dict(target)
        return await _ORIGINAL_FILL(*args, **kwargs)

    application_tasks.fill_and_submit_application = operator_target_aware_fill

    _ORIGINAL_CLAIM = handoff_session.claim_handoff_session

    def approval_gated_claim(db, session, *, user_id: int, resume_token: str):
        if session.challenge_type == HandoffChallengeType.final_submit.value:
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
        if session.challenge_type != HandoffChallengeType.final_submit.value:
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

        playwright, _, _, page = await browser_handoff._connect_local_cdp(session)
        try:
            before = await browser_handoff._verify_session_target(page, session)
            browser_handoff._require_verified_session_target(before)
            adapter = await browser_handoff.detect_ats_adapter(page, page.url)
            surface = await adapter.resolve_surface(page)
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

            await submit_control.click()
            await page.wait_for_timeout(900)
            confirmation = await browser_handoff._submission_confirmation_state(page)
            after = await browser_handoff._verify_session_target(
                page,
                session,
                allow_same_site_confirmation=bool(confirmation["submission_confirmed"]),
            )
            browser_handoff._require_verified_session_target(after)
            fingerprint = await browser_handoff.page_fingerprint(page)
            return {
                "action": action,
                "current_url": page.url,
                "current_fingerprint": fingerprint,
                "target_verification": after,
                "submission_confirmed": bool(confirmation["submission_confirmed"]),
                "sensitive_value_logged": False,
            }
        finally:
            await browser_handoff._disconnect(playwright)

    browser_handoff.perform_handoff_action = operator_locked_action

    _ORIGINAL_VERIFY_COMPLETION = browser_handoff.verify_browser_handoff_completion

    async def final_submit_confirmation_required(session):
        verification = await _ORIGINAL_VERIFY_COMPLETION(session)
        if (
            session.challenge_type == HandoffChallengeType.final_submit.value
            and not verification.evidence.get("submission_confirmed")
        ):
            verification.challenge_cleared = False
            verification.evidence["verification_method"] = (
                "operator_final_submit_confirmation_required"
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
