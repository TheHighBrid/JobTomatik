"""Focused Lever Phase A runtime compatibility fixes.

The hosted Lever form may expose invisible CAPTCHA plumbing or passive legal text
without presenting a human-verification widget. Those signals must not create a
retained interactive handoff. This module also keeps the synthetic certification
profile internally consistent for explicit Canada location, work-eligibility, and
salary-alignment questions.
"""

from __future__ import annotations

import re
import sys
from typing import Any, Dict, Iterable, Optional

from app.services import browser_navigation, lever_certification


_INSTALLED = False
_ORIGINAL_DETECT_BLOCKING_CHALLENGE = browser_navigation.detect_blocking_challenge
_ORIGINAL_CHOOSE_SYNTHETIC_ANSWER = lever_certification.choose_synthetic_answer


def _normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _matching_option(options: Iterable[str], *phrases: str) -> Optional[str]:
    values = [str(option) for option in options]
    for phrase in phrases:
        target = _normalized(phrase)
        for option in values:
            candidate = _normalized(option)
            if target and (candidate == target or target in candidate):
                return option
    return None


def _choose_synthetic_answer(
    descriptor: str,
    options: list[str],
    *,
    control_type: str,
) -> str:
    question = _normalized(descriptor)

    if any(
        phrase in question
        for phrase in (
            "located in canada",
            "based in canada",
            "reside in canada",
            "living in canada",
            "live in canada",
        )
    ):
        selected = _matching_option(options, "Yes")
        if selected is not None:
            return selected

    if any(
        phrase in question
        for phrase in (
            "authorized to work",
            "legally authorized",
            "work authorization",
            "eligible to work",
            "legally eligible",
            "permitted to work",
        )
    ):
        selected = _matching_option(options, "Yes")
        if selected is not None:
            return selected

    if "salary range" in question and any(
        phrase in question
        for phrase in (
            "expectations aligned",
            "expectation aligned",
            "aligned with it",
            "reviewed the posted salary",
        )
    ):
        selected = _matching_option(options, "Yes")
        if selected is not None:
            return selected

    if any(
        phrase in question
        for phrase in (
            "desired salary",
            "salary expectation",
            "expected salary",
            "compensation expectation",
        )
    ) and control_type in {"text", "textarea"}:
        return "150000"

    return _ORIGINAL_CHOOSE_SYNTHETIC_ANSWER(
        descriptor,
        options,
        control_type=control_type,
    )


async def _visible_captcha_evidence(page: Any) -> Optional[Dict[str, Any]]:
    selectors = (
        'iframe[src*="recaptcha" i]',
        'iframe[src*="hcaptcha" i]',
        'iframe[src*="challenges.cloudflare.com" i]',
        '[class*="captcha" i]',
        '[id*="captcha" i]',
        '[data-sitekey]',
    )
    for selector in selectors:
        evidence = await browser_navigation._visible_challenge_element(page, selector)
        if evidence:
            return evidence
    return None


async def _detect_blocking_challenge(page: Any) -> Optional[Dict[str, Any]]:
    """Refine inherited CAPTCHA results without widening any other boundary.

    The shared detector already handles login, MFA, anti-bot, and assessment pages.
    This wrapper only rejects invisible Lever CAPTCHA plumbing. It never rescans an
    entire job page for generic challenge words.
    """
    inherited = await _ORIGINAL_DETECT_BLOCKING_CHALLENGE(page)
    if inherited and inherited.get("reason_code") != "captcha_detected":
        return inherited

    response_state = await browser_navigation.captcha_response_state(page)
    if response_state["has_completed_response"]:
        return None

    visible_captcha = await _visible_captcha_evidence(page)
    if visible_captcha is not None:
        return {
            "reason_code": "captcha_detected",
            "summary": (
                "A visible CAPTCHA or human-verification challenge requires "
                "manual completion."
            ),
            "details": visible_captcha,
        }

    context = await browser_navigation.challenge_page_context(page)
    contextual = browser_navigation.classify_challenge_context(context)
    if contextual and contextual.get("reason_code") == "captcha_detected":
        return contextual
    return None


def _rebind_loaded_detector_aliases() -> None:
    """Replace cached imports that were bound before this compatibility layer."""
    for module_name in (
        "app.services.ats_flow",
        "app.services.browser_handoff",
        "app.services.form_filler_v2",
    ):
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "detect_blocking_challenge"):
            setattr(module, "detect_blocking_challenge", _detect_blocking_challenge)


def install_lever_phase_a_runtime_compat() -> None:
    global _INSTALLED
    browser_navigation.detect_blocking_challenge = _detect_blocking_challenge
    lever_certification.choose_synthetic_answer = _choose_synthetic_answer
    _rebind_loaded_detector_aliases()
    _INSTALLED = True


__all__ = ["install_lever_phase_a_runtime_compat"]
