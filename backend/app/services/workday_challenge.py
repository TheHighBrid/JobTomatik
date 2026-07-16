"""Install narrow Workday login and account-creation handoff detection.

The detector never enters credentials, creates an account, handles MFA, or mutates a
challenge. It only classifies an inaccessible boundary for the existing retained-
browser human handoff protocol.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.services.ats_workday import is_workday_host

_PASSWORD_SELECTORS = (
    'input[data-automation-id="password"]',
    'input[data-automation-id*="password" i]',
    'input[type="password"]',
    'input[autocomplete="current-password"]',
)
_CREATE_ACCOUNT_SELECTORS = (
    '[data-automation-id*="createAccount" i]',
    'button:has-text("Create Account")',
    'a:has-text("Create Account")',
    'button:has-text("Sign Up")',
    'a:has-text("Sign Up")',
)
_CREATE_ACCOUNT_PHRASES = (
    "create an account to apply",
    "create account",
    "create your candidate account",
    "sign up to continue",
    "register a new account",
)


def _workday_page(page: Any) -> bool:
    try:
        if is_workday_host(urlparse(str(getattr(page, "url", "") or "")).hostname or ""):
            return True
    except Exception:
        pass
    return False


def _handoff(reason_code: str, summary: str, boundary: str) -> Dict[str, Any]:
    return {
        "reason_code": reason_code,
        "summary": summary,
        "details": {
            "platform": "workday",
            "handoff_boundary": boundary,
            "credentials_entered": False,
            "account_created": False,
            "bypass_attempted": False,
        },
    }


async def detect_workday_login_or_account_boundary(page: Any) -> Optional[Dict[str, Any]]:
    if not _workday_page(page):
        marker_found = False
        for selector in (
            '[data-automation-id="jobPostingApplyButton"]',
            '[data-automation-id="bottom-navigation-next-button"]',
            'iframe[src*="myworkdayjobs.com" i]',
        ):
            try:
                if await page.query_selector(selector):
                    marker_found = True
                    break
            except Exception:
                continue
        if not marker_found:
            return None

    for selector in _PASSWORD_SELECTORS:
        try:
            control = await page.query_selector(selector)
            if control and await control.is_visible():
                value = _handoff(
                    "login_required",
                    "A Workday existing-account sign-in step requires manual completion.",
                    "pre_form_or_mid_flow",
                )
                value["details"]["selector"] = selector
                return value
        except Exception:
            continue

    for selector in _CREATE_ACCOUNT_SELECTORS:
        try:
            control = await page.query_selector(selector)
            if control and await control.is_visible():
                value = _handoff(
                    "account_creation_required",
                    "Workday candidate-account creation requires manual completion.",
                    "pre_form",
                )
                value["details"]["selector"] = selector
                return value
        except Exception:
            continue

    try:
        body = (await page.inner_text("body"))[:20000].lower()
    except Exception:
        body = ""
    phrase = next((item for item in _CREATE_ACCOUNT_PHRASES if item in body), "")
    if phrase:
        value = _handoff(
            "account_creation_required",
            "Workday candidate-account creation requires manual completion.",
            "pre_form",
        )
        value["details"]["matched_phrase"] = phrase
        return value
    return None


def install_workday_challenge_detection() -> None:
    """Wrap shared challenge detection with Workday-specific manual boundaries."""

    from app.services import ats_flow, browser_navigation

    current = browser_navigation.detect_blocking_challenge
    if getattr(current, "_jobtomatik_workday_boundaries", False):
        return

    async def detect_with_workday_boundaries(page: Any):
        existing = await current(page)
        if existing:
            return existing
        return await detect_workday_login_or_account_boundary(page)

    detect_with_workday_boundaries._jobtomatik_workday_boundaries = True
    browser_navigation.detect_blocking_challenge = detect_with_workday_boundaries
    ats_flow.detect_blocking_challenge = detect_with_workday_boundaries
