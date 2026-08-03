"""Focused Lever Phase A runtime compatibility fixes.

The hosted Lever form may expose invisible CAPTCHA plumbing or passive legal text
without presenting a human-verification widget. Those signals must not create a
retained interactive handoff. This module also keeps the synthetic certification
profile internally consistent for explicit Canada location, work-eligibility, and
salary-alignment questions.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from app.services import browser_navigation, lever_certification


_INSTALLED = False
_ORIGINAL_CHOOSE_SYNTHETIC_ANSWER = lever_certification.choose_synthetic_answer
_ACTIVE_CAPTCHA_TEXT = re.compile(
    r"verify you are human|confirm you are human|prove you are human|"
    r"(?:please\s+)?(?:complete|solve)\s+(?:the\s+)?(?:captcha|recaptcha|hcaptcha)|"
    r"(?:captcha|recaptcha|hcaptcha)\s+(?:is\s+)?(?:required|failed|expired|invalid)",
    flags=re.IGNORECASE,
)


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
        '[class*="captcha" i]',
        '[id*="captcha" i]',
    )
    for selector in selectors:
        try:
            elements = await page.query_selector_all(selector)
        except Exception:
            continue
        for element in elements:
            try:
                if not await element.is_visible():
                    continue
                source = str(await element.get_attribute("src") or "").lower()
                if "size=invisible" in source:
                    continue
                if await element.evaluate(
                    "(el) => Boolean(el.closest('.grecaptcha-badge'))"
                ):
                    continue
                box = await element.bounding_box()
                if not box:
                    continue
                width = float(box.get("width") or 0)
                height = float(box.get("height") or 0)
                if selector.startswith("iframe"):
                    if width < 120 or height < 40:
                        continue
                elif width < 20 or height < 20:
                    continue
                return {
                    "selector": selector,
                    "width": round(width, 2),
                    "height": round(height, 2),
                    "source": source[:300],
                    "visible": True,
                }
            except Exception:
                continue
    return None


async def _detect_blocking_challenge(page: Any) -> Optional[Dict[str, Any]]:
    response_state = await browser_navigation.captcha_response_state(page)
    captcha_completed = bool(response_state["has_completed_response"])

    if not captcha_completed:
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

    try:
        title = await page.title()
    except Exception:
        title = ""
    try:
        body = (await page.inner_text("body"))[:20000]
    except Exception:
        body = ""
    haystack = f"{title}\n{body}"

    if not captcha_completed and _ACTIVE_CAPTCHA_TEXT.search(haystack):
        return {
            "reason_code": "captcha_detected",
            "summary": (
                "A visible CAPTCHA or human-verification challenge requires "
                "manual completion."
            ),
            "details": {
                "matched_text": _ACTIVE_CAPTCHA_TEXT.pattern,
                "visible": True,
            },
        }

    for reason_code, pattern, summary in browser_navigation._BLOCKING_CHALLENGES:
        if reason_code == "captcha_detected":
            continue
        if pattern.search(haystack):
            return {
                "reason_code": reason_code,
                "summary": summary,
                "details": {"matched_text": pattern.pattern},
            }
    return None


def install_lever_phase_a_runtime_compat() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    browser_navigation.detect_blocking_challenge = _detect_blocking_challenge
    lever_certification.choose_synthetic_answer = _choose_synthetic_answer
    _INSTALLED = True


__all__ = ["install_lever_phase_a_runtime_compat"]
