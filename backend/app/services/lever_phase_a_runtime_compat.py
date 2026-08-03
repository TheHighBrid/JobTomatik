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
                if "size=invisible" in source or "invisible=true" in source:
                    continue

                presentation = await element.evaluate(
                    """(el) => {
                      const rect = el.getBoundingClientRect();
                      let node = el;
                      let effectiveOpacity = 1;
                      let hiddenByStyle = false;
                      let hiddenByAttribute = false;
                      let invisibleContainer = false;
                      let pointerEvents = '';

                      while (node && node.nodeType === Node.ELEMENT_NODE) {
                        const style = window.getComputedStyle(node);
                        const parsedOpacity = Number.parseFloat(style.opacity || '1');
                        effectiveOpacity *= Number.isFinite(parsedOpacity) ? parsedOpacity : 1;
                        hiddenByStyle = hiddenByStyle
                          || style.display === 'none'
                          || style.visibility === 'hidden'
                          || style.visibility === 'collapse';
                        hiddenByAttribute = hiddenByAttribute
                          || node.hidden
                          || node.getAttribute('aria-hidden') === 'true'
                          || node.hasAttribute('inert');
                        invisibleContainer = invisibleContainer
                          || String(node.getAttribute('data-size') || '').toLowerCase() === 'invisible'
                          || node.classList.contains('grecaptcha-badge');
                        if (node === el) {
                          pointerEvents = style.pointerEvents || '';
                        }
                        node = node.parentElement;
                      }

                      const intersectsViewport = rect.bottom > 0
                        && rect.right > 0
                        && rect.top < window.innerHeight
                        && rect.left < window.innerWidth;
                      let hitTested = null;
                      if (intersectsViewport && rect.width > 0 && rect.height > 0) {
                        const x = Math.max(0, Math.min(
                          window.innerWidth - 1,
                          rect.left + rect.width / 2
                        ));
                        const y = Math.max(0, Math.min(
                          window.innerHeight - 1,
                          rect.top + rect.height / 2
                        ));
                        const top = document.elementFromPoint(x, y);
                        hitTested = Boolean(
                          top && (top === el || el.contains(top) || top.contains(el))
                        );
                      }

                      return {
                        width: rect.width,
                        height: rect.height,
                        top: rect.top,
                        left: rect.left,
                        effectiveOpacity,
                        hiddenByStyle,
                        hiddenByAttribute,
                        invisibleContainer,
                        pointerEvents,
                        intersectsViewport,
                        hitTested,
                        title: el.getAttribute('title') || '',
                      };
                    }"""
                )

                if presentation.get("hiddenByStyle"):
                    continue
                if presentation.get("hiddenByAttribute"):
                    continue
                if presentation.get("invisibleContainer"):
                    continue
                if float(presentation.get("effectiveOpacity") or 0) <= 0.05:
                    continue
                if str(presentation.get("pointerEvents") or "").lower() == "none":
                    continue
                if (
                    presentation.get("intersectsViewport")
                    and presentation.get("hitTested") is False
                ):
                    continue

                width = float(presentation.get("width") or 0)
                height = float(presentation.get("height") or 0)
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
                    "title": str(presentation.get("title") or "")[:200],
                    "effective_opacity": round(
                        float(presentation.get("effectiveOpacity") or 0), 3
                    ),
                    "intersects_viewport": bool(
                        presentation.get("intersectsViewport")
                    ),
                    "hit_tested": presentation.get("hitTested"),
                    "visible": True,
                }
            except Exception:
                continue
    return None


async def _detect_blocking_challenge(page: Any) -> Optional[Dict[str, Any]]:
    """Refine inherited CAPTCHA results without erasing other ATS boundaries.

    Challenge detection is assembled through compatibility wrappers whose import
    order can vary across workers and test collection. The Lever layer therefore
    delegates first and only replaces a broad ``captcha_detected`` result with its
    stricter visibility check. Login, MFA, anti-bot, assessment, popup, and other
    adapter-specific handoffs pass through unchanged.
    """
    inherited = await _ORIGINAL_DETECT_BLOCKING_CHALLENGE(page)
    if inherited and inherited.get("reason_code") != "captcha_detected":
        return inherited

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

    # The inherited detector already evaluated every non-CAPTCHA boundary it knew
    # about. This fallback preserves base challenge patterns when the Lever wrapper
    # was installed before a later adapter-specific wrapper joined the chain.
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


def _rebind_loaded_detector_aliases() -> None:
    """Replace cached imports that were bound before this compatibility layer.

    ``ats_flow`` and ``browser_handoff`` import the detector directly. When a script
    imports ATS registry modules before ``form_filler``, those modules retain the old
    function object even after ``browser_navigation`` is patched. Rebind only the
    known shared detector aliases so adapter-specific wrappers remain untouched.
    """
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
