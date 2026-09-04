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
from urllib.parse import urlsplit

from app.models.handoff import HandoffChallengeType
from app.services import browser_navigation


_INSTALLED = False
_ORIGINAL_VERIFY_COMPLETION = None
_HARDENING_SENTINEL = "_jobtomatik_operator_live_pilot_hardening_v2"
_FINAL_VERIFY_ACTIVE: ContextVar[bool] = ContextVar(
    "jobtomatik_operator_final_verify_active",
    default=False,
)


def _challenge_type(session: Any) -> str:
    value = getattr(session, "challenge_type", None)
    return str(value or "")


def _trusted_provider_iframe(
    source: str,
    *,
    domains: tuple[str, ...],
    path_marker: str | None = None,
) -> bool:
    """Match an HTTPS provider iframe by parsed hostname, never URL substring."""

    try:
        parsed = urlsplit(source)
        hostname = str(parsed.hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return False
    if parsed.scheme.lower() != "https" or not hostname:
        return False
    if not any(hostname == domain or hostname.endswith(f".{domain}") for domain in domains):
        return False
    return path_marker is None or path_marker in parsed.path.lower()


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

    hcaptcha_loaded = bool(
        globals_state["hcaptcha"]
        or any(
            _trusted_provider_iframe(source, domains=("hcaptcha.com",))
            for source in iframe_sources
        )
    )
    grecaptcha_loaded = bool(
        globals_state["grecaptcha"]
        or any(
            _trusted_provider_iframe(
                source,
                domains=("google.com", "recaptcha.net"),
                path_marker="recaptcha",
            )
            for source in iframe_sources
        )
    )
    turnstile_loaded = bool(
        globals_state["turnstile"]
        or any(
            _trusted_provider_iframe(
                source,
                domains=("challenges.cloudflare.com",),
            )
            for source in iframe_sources
        )
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

    global _INSTALLED, _ORIGINAL_VERIFY_COMPLETION

    from app.services import browser_handoff
    if (
        getattr(browser_handoff.verify_browser_handoff_completion, _HARDENING_SENTINEL, False)
    ):
        _INSTALLED = True
        return

    _ORIGINAL_VERIFY_COMPLETION = browser_handoff.verify_browser_handoff_completion

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

    setattr(hardened_verify_completion, _HARDENING_SENTINEL, True)

    browser_handoff.verify_browser_handoff_completion = hardened_verify_completion

    try:
        from app.api import handoffs as handoff_api

        handoff_api.verify_browser_handoff_completion = hardened_verify_completion
    except Exception:
        pass

    _INSTALLED = True


__all__ = [
    "install_operator_assisted_live_pilot_hardening",
    "passive_verification_requires_manual_browser",
    "passive_verification_state",
]
