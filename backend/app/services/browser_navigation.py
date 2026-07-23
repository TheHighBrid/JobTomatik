"""Navigation and manual-handoff detection for application browser sessions."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from app.services.control_engine import normalize_text

JOB_BANK_DOMAINS = (
    "jobbank.gc.ca",
    "guichetemplois.gc.ca",
)
LINKEDIN_DOMAINS = ("linkedin.com",)
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
    '#jobs-apply-button-id',
    'a.jobs-apply-button',
    'button.jobs-apply-button',
    '[data-tracking-control-name*="apply-link-offsite" i]',
    'a:has-text("Apply")',
    'button:has-text("Apply")',
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


def _host_matches(hostname: str, domains: tuple[str, ...]) -> bool:
    host = (hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def _is_job_board_url(url: str) -> bool:
    hostname = (urlparse(url or "").hostname or "").lower()
    return (
        _host_matches(hostname, JOB_BANK_DOMAINS)
        or _host_matches(hostname, LINKEDIN_DOMAINS)
    )


def _is_linkedin_listing(url: str) -> bool:
    parsed = urlparse(url or "")
    hostname = (parsed.hostname or "").lower()
    return (
        _host_matches(hostname, LINKEDIN_DOMAINS)
        and any(fragment in parsed.path for fragment in LINKEDIN_LISTING_PATHS)
    )


def _is_listing(url: str) -> bool:
    parsed = urlparse(url or "")
    hostname = (parsed.hostname or "").lower()
    if _host_matches(hostname, JOB_BANK_DOMAINS):
        return any(fragment in parsed.path for fragment in JOB_BANK_LISTING_PATHS)
    if _host_matches(hostname, LINKEDIN_DOMAINS):
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


async def _external_target_after_control_click(
    page: Any,
    original_url: str,
    log: List[Dict[str, Any]],
    selector: str,
) -> Optional[Dict[str, Any]]:
    """Return an employer destination reached by an Apply control.

    LinkedIn may navigate the current page or open an employer URL in a new page.
    The form runner continues with the original page object, so a popup destination
    is copied back into that page before returning.
    """
    await page.wait_for_timeout(1000)

    candidates = [page]
    try:
        for candidate in list(page.context.pages):
            if candidate not in candidates:
                candidates.append(candidate)
    except Exception:
        pass

    for candidate in reversed(candidates):
        target_url = str(getattr(candidate, "url", "") or "")
        if not target_url or target_url == original_url or _is_job_board_url(target_url):
            continue

        if candidate is not page:
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                target_url = page.url
            except Exception as exc:
                log.append({
                    "action": "external_apply_popup_copy_failed",
                    "url": target_url,
                    "detail": str(exc)[:200],
                    "ts": now_iso(),
                })

        log.append({
            "action": "external_apply_control_navigated",
            "url": target_url,
            "selector": selector,
            "ts": now_iso(),
        })
        return {"application_url": target_url}

    return None


async def navigate_job_board_listing(page, log: List[Dict[str, Any]]) -> Dict[str, Any]:
    current_url = page.url
    if not _is_listing(current_url):
        return {}
    log.append({"action": "listing_page_detected", "url": current_url, "ts": now_iso()})

    for selector in REVEAL_APPLY_SELECTORS:
        try:
            control = await page.query_selector(selector)
            if control and await control.is_visible() and await control.is_enabled():
                await control.click(timeout=5000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                log.append({
                    "action": "apply_control_clicked",
                    "selector": selector,
                    "ts": now_iso(),
                })
                external = await _external_target_after_control_click(
                    page,
                    current_url,
                    log,
                    selector,
                )
                if external:
                    return external
                break
        except Exception as exc:
            log.append({
                "action": "apply_control_skipped",
                "selector": selector,
                "detail": str(exc)[:160],
                "ts": now_iso(),
            })

    scan_url = page.url or current_url
    await page.wait_for_timeout(1000)
    for anchor in await page.query_selector_all("a[href]"):
        href = await anchor.get_attribute("href") or ""
        text = normalize_text(await anchor.inner_text())
        if not _probable_apply_href(href, scan_url) and not any(
            hint in text for hint in APPLY_LINK_HINTS
        ):
            continue

        target = urljoin(scan_url, href)
        if target.startswith("mailto:"):
            email = target.removeprefix("mailto:").split("?", 1)[0]
            log.append({"action": "email_apply_detected", "email": email, "ts": now_iso()})
            return {
                "manual_review_only": True,
                "contact_email": email,
                "reason": "Employer accepts applications by email; review and send manually.",
            }
        if _is_job_board_url(target):
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
            return {
                "manual_review_only": True,
                "application_url": target,
                "reason": "The employer Apply URL was found, but the browser could not open it.",
            }

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
    reason = (
        "LinkedIn was opened, but no outbound employer Apply destination could be resolved."
        if _is_linkedin_listing(current_url)
        else "No external employer application destination could be resolved from the listing."
    )
    return {
        "manual_review_only": True,
        "application_url": current_url,
        "reason": reason,
    }


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
