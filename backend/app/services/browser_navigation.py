"""Navigation and manual-handoff detection for application browser sessions."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from app.services.control_engine import normalize_text

JOB_BOARD_HOSTS = {
    "jobbank.gc.ca", "www.jobbank.gc.ca",
    "guichetemplois.gc.ca", "www.guichetemplois.gc.ca",
    "linkedin.com", "www.linkedin.com",
}
JOB_BANK_LISTING_PATHS = (
    "/jobsearch/jobposting/",
    "/rechercheemplois/offredemploi/",
)
LINKEDIN_LISTING_PATHS = (
    "/jobs/view/",
    "/jobs/collections/",
)
_FAKE_URL_RE = re.compile(r"/jobs/[0-9a-f]{12,20}/?$", re.IGNORECASE)
APPLY_LINK_HINTS = ("apply", "application", "career", "careers", "recruit", "mailto:")
REVEAL_APPLY_SELECTORS = [
    'button:has-text("Show how to apply")',
    'a:has-text("Show how to apply")',
    'button:has-text("How to apply")',
    'a:has-text("How to apply")',
    'button:has-text("Apply now")',
    'a:has-text("Apply now")',
    '[aria-controls*="apply" i]',
    '[data-cy*="apply" i]',
    '[id*="apply" i]',
]
SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Submit Application")',
    'button:has-text("Submit my application")',
    'button:has-text("Submit")',
    'button:has-text("Send Application")',
    'button:has-text("Complete Application")',
    'button:has-text("Finish")',
    '[data-testid*="submit"]',
    '[aria-label*="submit" i]',
]
_BLOCKING_CHALLENGES = [
    (
        "captcha_detected",
        re.compile(r"captcha|recaptcha|hcaptcha|verify you are human", re.IGNORECASE),
        "A CAPTCHA or human-verification challenge requires manual completion.",
    ),
    (
        "anti_bot_challenge",
        re.compile(r"cloudflare|checking your browser|security challenge|unusual traffic", re.IGNORECASE),
        "A security challenge requires manual completion.",
    ),
    (
        "mfa_required",
        re.compile(r"verification code|two-factor|multi-factor|one-time code|mfa", re.IGNORECASE),
        "A multi-factor authentication step requires manual completion.",
    ),
    (
        "assessment_required",
        re.compile(r"complete (?:the|an) assessment|skills assessment|take (?:the|a) test", re.IGNORECASE),
        "An employer assessment requires manual completion.",
    ),
]


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_fake_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.hostname in {"example.com", "localhost", "127.0.0.1"}:
        return True
    return bool(_FAKE_URL_RE.search(parsed.path))


def _is_listing(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if hostname in {"jobbank.gc.ca", "www.jobbank.gc.ca", "guichetemplois.gc.ca", "www.guichetemplois.gc.ca"}:
        return any(fragment in parsed.path for fragment in JOB_BANK_LISTING_PATHS)
    if hostname in {"linkedin.com", "www.linkedin.com"}:
        return any(fragment in parsed.path for fragment in LINKEDIN_LISTING_PATHS)
    return False


def _probable_apply_href(href: str, current_url: str) -> bool:
    lowered = href.lower()
    if lowered.startswith("mailto:"):
        return True
    if not any(hint in lowered for hint in APPLY_LINK_HINTS):
        return False
    parsed = urlparse(urljoin(current_url, href))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def navigate_job_board_listing(page, log: List[Dict[str, Any]]) -> Dict[str, Any]:
    current_url = page.url
    if not _is_listing(current_url):
        return {}
    log.append({"action": "listing_page_detected", "url": current_url, "ts": now_iso()})

    for selector in REVEAL_APPLY_SELECTORS:
        try:
            control = await page.query_selector(selector)
            if control:
                await control.click(timeout=5000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                log.append({
                    "action": "apply_instructions_revealed",
                    "selector": selector,
                    "ts": now_iso(),
                })
                break
        except Exception as exc:
            log.append({
                "action": "apply_reveal_skipped",
                "selector": selector,
                "detail": str(exc)[:160],
                "ts": now_iso(),
            })

    await page.wait_for_timeout(1000)
    for anchor in await page.query_selector_all("a[href]"):
        href = await anchor.get_attribute("href") or ""
        text = normalize_text(await anchor.inner_text())
        if not _probable_apply_href(href, current_url) and not any(
            hint in text for hint in APPLY_LINK_HINTS
        ):
            continue

        target = urljoin(current_url, href)
        if target.startswith("mailto:"):
            email = target.removeprefix("mailto:").split("?", 1)[0]
            log.append({"action": "email_apply_detected", "email": email, "ts": now_iso()})
            return {
                "manual_review_only": True,
                "contact_email": email,
                "reason": "Employer accepts applications by email; review and send manually.",
            }
        if urlparse(target).netloc in JOB_BOARD_HOSTS:
            continue

        log.append({
            "action": "external_apply_link_found",
            "url": target,
            "text": text[:120],
            "ts": now_iso(),
        })
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            log.append({"action": "external_apply_navigated", "url": page.url, "ts": now_iso()})
            return {"application_url": page.url}
        except Exception as exc:
            log.append({
                "action": "external_apply_navigation_failed",
                "url": target,
                "detail": str(exc)[:200],
                "ts": now_iso(),
            })
            return {"application_url": target}

    body = await page.inner_text("body")
    email_match = re.search(
        r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", body, flags=re.IGNORECASE
    )
    if email_match:
        email = email_match.group(0)
        log.append({"action": "email_apply_detected", "email": email, "ts": now_iso()})
        return {
            "manual_review_only": True,
            "contact_email": email,
            "reason": "Employer accepts applications by email; review and send manually.",
        }
    log.append({"action": "apply_target_not_found", "url": current_url, "ts": now_iso()})
    return {}


async def detect_blocking_challenge(page) -> Optional[Dict[str, Any]]:
    for selector in (
        'iframe[src*="recaptcha" i]',
        'iframe[src*="hcaptcha" i]',
        '[class*="captcha" i]',
        '[id*="captcha" i]',
    ):
        try:
            if await page.query_selector(selector):
                return {
                    "reason_code": "captcha_detected",
                    "summary": "A CAPTCHA or human-verification challenge requires manual completion.",
                    "details": {"selector": selector},
                }
        except Exception:
            pass

    try:
        title = await page.title()
    except Exception:
        title = ""
    try:
        body = (await page.inner_text("body"))[:20000]
    except Exception:
        body = ""
    haystack = f"{title}\n{body}"
    for reason_code, pattern, summary in _BLOCKING_CHALLENGES:
        if pattern.search(haystack):
            return {
                "reason_code": reason_code,
                "summary": summary,
                "details": {"matched_text": pattern.pattern},
            }
    return None


async def find_submit_button(page):
    for selector in SUBMIT_SELECTORS:
        try:
            button = await page.query_selector(selector)
            if button and await button.is_visible() and await button.is_enabled():
                return button
        except Exception:
            pass
    return None
