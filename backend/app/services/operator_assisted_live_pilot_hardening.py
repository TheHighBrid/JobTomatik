"""Live-pilot hardening for operator-assisted final submission.

The Maple physical pilot exposed two production-only hazards:

1. Lever can load passive hCaptcha infrastructure without presenting a visible
   challenge or a completed response token. A CDP-driven final click is then rejected
   by Lever's verification layer. In that state JobTomatik must fail closed before any
   employer-side click and require the owner to finish in a normal browser.
2. Compatibility wrappers around retained-browser confirmation can be installed in
   different orders. Final-submit confirmation must not depend on a wrapper chain that
   can recurse after a consequential click.

This module does not solve or bypass CAPTCHA. It only detects the passive verification
boundary and keeps final confirmation verification self-contained for final-submit
handoffs.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict

from app.models.handoff import HandoffChallengeType
from app.services import browser_navigation


_INSTALLED = False
_ORIGINAL_PERFORM_ACTION = None
_ORIGINAL_VERIFY_COMPLETION = None
_HARDENING_SENTINEL = "_jobtomatik_operator_live_pilot_hardening_v1"


def _challenge_type(session: Any) -> str:
    value = getattr(session, "challenge_type", None)
    return str(value or "")


async def passive_verification_state(page: Any) -> Dict[str, Any]:
    """Inspect CAPTCHA provider state without interacting with any challenge."""

    response_state = await browser_navigation.captcha_response_state(page)
    globals_state: Dict[str, bool] = {
        "hcaptcha": False,
        "grecaptcha": False,
        "turnstile": False,
    }
    try:
        observed = await page.evaluate(
            """() => ({
              hcaptcha: typeof window.hcaptcha !== 'undefined',
              grecaptcha: typeof window.grecaptcha !== 'undefined',
              turnstile: typeof window.turnstile !== 'undefined'
            })"""
        )
        if isinstance(observed, dict):
            globals_state.update({
                key: bool(observed.get(key))
                for key in globals_state
            })
    except Exception:
        pass

    iframe_sources: list[str] = []
    try:
        for element in await page.query_selector_all("iframe[src]"):
            source = str(await element.get_attribute("src") or "")
            if source:
                iframe_sources.append(source)
    except Exception:
        pass

    lowered_sources = [source.lower() for source in iframe_sources]
    hcaptcha_loaded = bool(
        globals_state["hcaptcha"]
        or any("hcaptcha.com" in source for source in lowered_sources)
    )
    grecaptcha_loaded = bool(
        globals_state["grecaptcha"]
        or any("recaptcha" in source for source in lowered_sources)
    )
    turnstile_loaded = bool(
        globals_state["turnstile"]
        or any("challenges.cloudflare.com" in source for source in lowered_sources)
    )

    completed = bool(response_state.get("has_completed_response"))
    return {
        "responses": list(response_state.get("responses") or []),
        "has_completed_response": completed,
        "hcaptcha_loaded": hcaptcha_loaded,
        "grecaptcha_loaded": grecaptcha_loaded,
        "turnstile_loaded": turnstile_loaded,
        "manual_browser_required": bool(hcaptcha_loaded and not completed),
    }


def passive_verification_requires_manual_browser(state: Dict[str, Any]) -> bool:
    """Pure predicate used by tests and the final-action gate."""

    return bool(
        state.get("hcaptcha_loaded")
        and not state.get("has_completed_response")
    )


async def _verify_final_submit_without_wrapper_chain(browser_handoff, session):
    """Verify a final-submit handoff without calling the wrapped verifier again."""

    playwright, _, context, page = await browser_handoff._connect_local_cdp(session)
    try:
        fingerprint = await browser_handoff.page_fingerprint(page)
        confirmation = await browser_handoff._submission_confirmation_state(page)
        target_verification = await browser_handoff._verify_session_target(
            page,
            session,
            allow_same_site_confirmation=bool(confirmation["submission_confirmed"]),
        )

        metadata = dict(getattr(session, "handoff_metadata", None) or {})
        target_verified = bool(target_verification.get("verified"))
        strong_confirmation_observed = bool(
            metadata.get("operator_submit_confirmation_observed") is True
        )
        generic_confirmation = bool(confirmation.get("submission_confirmed"))
        confirmation_url_signal = bool(confirmation.get("confirmation_url_signal"))
        live_snapshot_checkpointed = bool(
            metadata.get("operator_submit_live_snapshot_checkpointed") is True
        )
        pre_submit_url = str(metadata.get("operator_submit_pre_submit_url") or "")
        current_url = str(getattr(page, "url", "") or "")
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

        evidence: Dict[str, Any] = {
            **confirmation,
            "target_verification": target_verification,
            "operator_submit_confirmation_observed": strong_confirmation_observed,
            "operator_submit_live_snapshot_checkpointed": live_snapshot_checkpointed,
            "provable_confirmation_transition": provable_confirmation_transition,
            "submission_confirmed": final_confirmed,
            "verification_method": (
                "operator_final_submit_strict_confirmation"
                if final_confirmed
                else "operator_final_submit_confirmation_required"
            ),
        }
        if not final_confirmed:
            evidence["passive_verification_state"] = await passive_verification_state(page)

        storage_state = await context.storage_state()
        evidence["storage_state_hash"] = hashlib.sha256(
            repr(storage_state).encode("utf-8")
        ).hexdigest()

        return browser_handoff.BrowserVerification(
            challenge_cleared=final_confirmed,
            provider=session.browser_provider,
            current_url=current_url,
            current_fingerprint=fingerprint,
            evidence=evidence,
        )
    finally:
        await browser_handoff._disconnect(playwright)


def install_operator_assisted_live_pilot_hardening() -> None:
    """Install idempotent final-action and final-confirmation hardening."""

    global _INSTALLED, _ORIGINAL_PERFORM_ACTION, _ORIGINAL_VERIFY_COMPLETION

    from app.services import browser_handoff

    if (
        getattr(browser_handoff.perform_handoff_action, _HARDENING_SENTINEL, False)
        and getattr(browser_handoff.verify_browser_handoff_completion, _HARDENING_SENTINEL, False)
    ):
        _INSTALLED = True
        return

    _ORIGINAL_PERFORM_ACTION = browser_handoff.perform_handoff_action
    _ORIGINAL_VERIFY_COMPLETION = browser_handoff.verify_browser_handoff_completion

    async def hardened_perform_action(
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
        if (
            _challenge_type(session) == HandoffChallengeType.final_submit.value
            and action == "operator_submit"
        ):
            playwright, _, _, page = await browser_handoff._connect_local_cdp(session)
            try:
                verification_state = await passive_verification_state(page)
            finally:
                await browser_handoff._disconnect(playwright)

            if passive_verification_requires_manual_browser(verification_state):
                raise browser_handoff.BrowserHandoffError(
                    "Lever loaded passive hCaptcha verification without a completed "
                    "response. JobTomatik will not click Submit in the retained CDP "
                    "browser. Finish the exact prepared application in a normal user "
                    "browser and capture employer confirmation evidence."
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

    async def hardened_verify_completion(session):
        if _challenge_type(session) == HandoffChallengeType.final_submit.value:
            return await _verify_final_submit_without_wrapper_chain(
                browser_handoff,
                session,
            )
        return await _ORIGINAL_VERIFY_COMPLETION(session)

    setattr(hardened_perform_action, _HARDENING_SENTINEL, True)
    setattr(hardened_verify_completion, _HARDENING_SENTINEL, True)

    browser_handoff.perform_handoff_action = hardened_perform_action
    browser_handoff.verify_browser_handoff_completion = hardened_verify_completion

    try:
        from app.api import handoffs as handoff_api

        handoff_api.perform_handoff_action = hardened_perform_action
        handoff_api.verify_browser_handoff_completion = hardened_verify_completion
    except Exception:
        pass

    _INSTALLED = True


__all__ = [
    "install_operator_assisted_live_pilot_hardening",
    "passive_verification_requires_manual_browser",
    "passive_verification_state",
]
