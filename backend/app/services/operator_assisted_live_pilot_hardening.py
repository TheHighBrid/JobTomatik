"""Live-pilot hardening for operator-assisted final submission.

The Maple physical pilot exposed two production-only hazards:

1. Lever can load passive hCaptcha infrastructure without presenting a visible
   challenge or a completed response token. A CDP-driven final click is then rejected
   by Lever's verification layer. In that state JobTomatik must fail closed before any
   employer-side click and require the owner to finish in a normal browser.
2. Compatibility wrappers around retained-browser confirmation can be installed in
   different orders. A recursive wrapper chain must fail closed instead of exhausting
   the Python stack after a consequential click.

This module does not solve or bypass CAPTCHA. It only detects the passive verification
boundary and adds a fail-closed reentrancy fuse around the established strict final
confirmation verifier.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict

from app.models.handoff import HandoffChallengeType
from app.services import browser_navigation


_INSTALLED = False
_ORIGINAL_PERFORM_ACTION = None
_ORIGINAL_VERIFY_COMPLETION = None
_HARDENING_SENTINEL = "_jobtomatik_operator_live_pilot_hardening_v2"
_FINAL_VERIFY_ACTIVE: ContextVar[bool] = ContextVar(
    "jobtomatik_operator_final_verify_active",
    default=False,
)


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
    """Return whether passive hCaptcha requires normal-browser completion."""

    return bool(
        state.get("hcaptcha_loaded")
        and not state.get("has_completed_response")
    )


def _reentrant_verification_result(browser_handoff, session):
    """Return deterministic fail-closed evidence instead of recursing forever."""

    return browser_handoff.BrowserVerification(
        challenge_cleared=False,
        provider=str(getattr(session, "browser_provider", "") or "unknown"),
        current_url=str(getattr(session, "current_url", "") or ""),
        current_fingerprint=str(getattr(session, "current_fingerprint", "") or ""),
        evidence={
            "submission_confirmed": False,
            "operator_submit_confirmation_observed": False,
            "provable_confirmation_transition": False,
            "reentrant_verification_blocked": True,
            "verification_method": "operator_final_submit_reentrancy_blocked",
            "automatic_retry_allowed": False,
        },
    )


def install_operator_assisted_live_pilot_hardening() -> None:
    """Install idempotent passive-verification and recursion hardening."""

    global _INSTALLED, _ORIGINAL_PERFORM_ACTION, _ORIGINAL_VERIFY_COMPLETION

    from app.services import browser_handoff
    from app.services import operator_assisted_handoff_integration as operator_integration

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
        is_final_submit = bool(
            _challenge_type(session) == HandoffChallengeType.final_submit.value
            and action == "operator_submit"
        )
        if is_final_submit:
            # Preserve the established safety ordering. Emergency stops, platform
            # disables, and runtime-mode drift must reject the action before any
            # retained-browser connection is attempted.
            blockers = operator_integration._operator_final_action_blockers(
                str(getattr(session, "current_url", "") or "")
            )
            if blockers:
                raise browser_handoff.BrowserHandoffError(
                    "Operator-assisted final submit is blocked by the current runtime profile: "
                    + ", ".join(blockers)
                )

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
        if _challenge_type(session) != HandoffChallengeType.final_submit.value:
            return await _ORIGINAL_VERIFY_COMPLETION(session)

        if _FINAL_VERIFY_ACTIVE.get():
            return _reentrant_verification_result(browser_handoff, session)

        token = _FINAL_VERIFY_ACTIVE.set(True)
        try:
            # Delegate to the already-established strict final-submit verifier. The
            # ContextVar above prevents an accidental compatibility-wrapper cycle from
            # recursing indefinitely while preserving its existing test seams and
            # target/confirmation invariants.
            return await _ORIGINAL_VERIFY_COMPLETION(session)
        finally:
            _FINAL_VERIFY_ACTIVE.reset(token)

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
