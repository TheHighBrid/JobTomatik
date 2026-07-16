"""Install explicit detection for SmartRecruiters' pre-form DataDome boundary.

The detector does not interact with, solve, bypass, or mutate the challenge. It
only classifies the blocking page so the existing secure manual-handoff protocol
can retain the browser session and report an accurate reason code.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_DATADOME_SELECTORS = (
    'iframe[src*="captcha-delivery.com" i]',
    'iframe[src*="datadome" i]',
    '[data-captcha-provider="datadome" i]',
)


def _challenge() -> Dict[str, Any]:
    return {
        "reason_code": "anti_bot_challenge",
        "summary": "A SmartRecruiters security challenge requires manual completion.",
        "details": {
            "provider": "datadome",
            "platform": "smartrecruiters",
            "handoff_boundary": "pre_form",
            "bypass_attempted": False,
        },
    }


async def detect_smartrecruiters_datadome(page: Any) -> Optional[Dict[str, Any]]:
    for selector in _DATADOME_SELECTORS:
        try:
            if await page.query_selector(selector):
                value = _challenge()
                value["details"]["selector"] = selector
                return value
        except Exception:
            continue

    for frame in getattr(page, "frames", []):
        try:
            url = str(getattr(frame, "url", "") or "").lower()
        except Exception:
            continue
        if "captcha-delivery.com/captcha" in url or "datadome" in url:
            value = _challenge()
            value["details"]["frame_url_host"] = (
                "captcha-delivery.com" if "captcha-delivery.com" in url else "datadome"
            )
            return value
    return None


def install_smartrecruiters_challenge_detection() -> None:
    """Wrap shared challenge detection with a narrow DataDome classifier."""
    from app.services import ats_flow, browser_navigation

    current = browser_navigation.detect_blocking_challenge
    if getattr(current, "_jobtomatik_smartrecruiters_datadome", False):
        return

    async def detect_with_smartrecruiters_datadome(page: Any):
        existing = await current(page)
        if existing:
            return existing
        return await detect_smartrecruiters_datadome(page)

    detect_with_smartrecruiters_datadome._jobtomatik_smartrecruiters_datadome = True
    browser_navigation.detect_blocking_challenge = detect_with_smartrecruiters_datadome
    ats_flow.detect_blocking_challenge = detect_with_smartrecruiters_datadome
