"""Navigation and manual-handoff detection for application browser sessions."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from app.services.control_engine import normalize_text

JOB_BANK_DOMAINS = ("jobbank.gc.ca", "guichetemplois.gc.ca")
LINKEDIN_DOMAINS = ("linkedin.com",)
JOB_BANK_LISTING_PATHS = (
    "/jobsearch/jobposting/",
    "/rechercheemplois/offredemploi/",
)
LINKEDIN_LISTING_PATHS = ("/jobs/view/", "/jobs/collections/")
_FAKE_URL_RE = re.compile(r"/jobs/[0-9a-f]{12,20}/?$", re.IGNORECASE)
APPLY_LINK_HINTS = ("apply", "application", "career", "careers", "recruit", "mailto:")
REVEAL_APPLY_SELECTORS = [
    '#jobs-apply-button-id',
    'a.jobs-apply-button',
    'button.jobs-apply-button',
    '[data-tracking-control-name*="apply-link-offsite" i]',
    'a[aria-label*="apply" i]',
    'button[aria-label*="apply" i]',
    'button:has-text("Show how to apply")',
    'a:has-text("Show how to apply")',
    'button:has-text("How to apply")',
    'a:has-text("How to apply")',
    'button:has-text("Apply now")',
    'a:has-text("Apply now")',
    '[aria-controls*="apply" i]',
    '[data-cy*="apply" i]',
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
CAPTCHA_RESPONSE_SELECTORS = (
    'textarea[name="g-recaptcha-response"]',
    'textarea[name="h-captcha-response"]',
    'input[name="cf-turnstile-response"]',
    'textarea[name="cf-turnstile-response"]',
)
_VISIBLE_CAPTCHA_SELECTORS = (
    'iframe[src*="recaptcha" i]',
    'iframe[src*="hcaptcha" i]',
    'iframe[src*="challenges.cloudflare.com" i]',
    '[class*="captcha" i]',
    '[id*="captcha" i]',
    '[data-sitekey]',
)
_BLOCKING_CHALLENGES = [
    (
        "captcha_detected",
        re.compile(
            r"verify you are human|confirm you are human|prove you are human|"
            r"(?:complete|solve)\s+(?:the\s+)?(?:captcha|recaptcha|hcaptcha)|"
            r"(?:captcha|recaptcha|hcaptcha)\s+(?:is\s+)?(?:required|failed|expired|invalid)",
            re.IGNORECASE,
        ),
        "A CAPTCHA or human-verification challenge requires manual completion.",
    ),
    (
        "anti_bot_challenge",
        re.compile(
            r"checking your browser|unusual traffic|access denied|security verification|"
            r"browser integrity check|cloudflare ray id|attention required",
            re.IGNORECASE,
        ),
        "A security challenge requires manual completion.",
    ),
    (
        "mfa_required",
        re.compile(
            r"enter (?:the|your|a) verification code|two-factor authentication|"
            r"multi-factor authentication|one-time (?:passcode|code)|authenticator code",
            re.IGNORECASE,
        ),
        "A multi-factor authentication step requires manual completion.",
    ),
    (
        "assessment_required",
        re.compile(
            r"begin (?:the|your|an) assessment|complete (?:the|your|an) assessment to continue|"
            r"start (?:the|your|an) skills assessment|take (?:the|your|an) required test",
            re.IGNORECASE,
        ),
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


def is_job_board_url(url: str) -> bool:
    hostname = (urlparse(url or "").hostname or "").lower()
    return _host_matches(hostname, JOB_BANK_DOMAINS) or _host_matches(hostname, LINKEDIN_DOMAINS)


def is_linkedin_listing(url: str) -> bool:
    parsed = urlparse(url or "")
    return _host_matches(parsed.hostname or "", LINKEDIN_DOMAINS) and any(
        fragment in (parsed.path or "") for fragment in LINKEDIN_LISTING_PATHS
    )


def _is_listing(url: str) -> bool:
    parsed = urlparse(url or "")
    hostname = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if _host_matches(hostname, JOB_BANK_DOMAINS):
        return any(fragment in path for fragment in JOB_BANK_LISTING_PATHS)
    if _host_matches(hostname, LINKEDIN_DOMAINS):
        return any(fragment in path for fragment in LINKEDIN_LISTING_PATHS)
    return False


def _probable_apply_href(href: str, current_url: str) -> bool:
    lowered = href.lower()
    if lowered.startswith("mailto:"):
        return True
    if not any(hint in lowered for hint in APPLY_LINK_HINTS):
        return False
    parsed = urlparse(urljoin(current_url, href))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def _control_is_actionable(control: Any) -> bool:
    try:
        visible = await control.is_visible()
    except (AttributeError, TypeError):
        visible = True
    try:
        enabled = await control.is_enabled()
    except (AttributeError, TypeError):
        enabled = True
    return bool(visible and enabled)


async def external_target_from_browser(
    page: Any,
    source_url: str,
    log: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Find an employer destination in the current page or any newly opened tab."""
    candidates = [page]
    try:
        for candidate in list(page.context.pages):
            if candidate not in candidates:
                candidates.append(candidate)
    except Exception:
        pass

    for candidate in reversed(candidates):
        target_url = str(getattr(candidate, "url", "") or "")
        if not target_url or target_url == source_url or is_job_board_url(target_url):
            continue
        parsed = urlparse(target_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if log is not None:
            log.append({
                "action": "external_application_target_observed",
                "url": target_url,
                "source_url": source_url,
                "ts": now_iso(),
            })
        return target_url
    return None


async def wait_for_external_application_target(
    page: Any,
    source_url: str,
    *,
    timeout_seconds: int,
    log: List[Dict[str, Any]],
) -> Optional[str]:
    """Wait for a user or the page to open an employer application destination."""
    timeout = max(0, int(timeout_seconds or 0))
    if timeout <= 0:
        return await external_target_from_browser(page, source_url, log)

    log.append({
        "action": "application_target_human_window_started",
        "source_url": source_url,
        "timeout_seconds": timeout,
        "ts": now_iso(),
    })
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        target = await external_target_from_browser(page, source_url, log)
        if target:
            log.append({
                "action": "application_target_human_window_completed",
                "url": target,
                "ts": now_iso(),
            })
            return target
        await page.wait_for_timeout(1000)
    log.append({
        "action": "application_target_human_window_expired",
        "source_url": source_url,
        "timeout_seconds": timeout,
        "ts": now_iso(),
    })
    return None


async def _copy_target_to_primary_page(
    page: Any,
    target_url: str,
    log: List[Dict[str, Any]],
) -> str:
    if page.url == target_url:
        return target_url
    try:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        return page.url
    except Exception as exc:
        log.append({
            "action": "external_apply_popup_copy_failed",
            "url": target_url,
            "detail": str(exc)[:200],
            "ts": now_iso(),
        })
        return target_url


async def navigate_job_board_listing(page, log: List[Dict[str, Any]]) -> Dict[str, Any]:
    current_url = page.url
    if not _is_listing(current_url):
        return {}
    log.append({"action": "listing_page_detected", "url": current_url, "ts": now_iso()})

    for selector in REVEAL_APPLY_SELECTORS:
        try:
            control = await page.query_selector(selector)
            if control and await _control_is_actionable(control):
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
                await page.wait_for_timeout(1000)
                target = await external_target_from_browser(page, current_url, log)
                if target:
                    target = await _copy_target_to_primary_page(page, target, log)
                    return {"application_url": target, "resolution_method": "apply_control"}
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
    try:
        anchors = page.locator("a[href]")
        anchor_count = await anchors.count()
    except Exception:
        anchors = None
        anchor_count = 0
    for index in range(anchor_count):
        anchor = anchors.nth(index)
        try:
            href = await anchor.get_attribute("href") or ""
            text = normalize_text(await anchor.inner_text())
        except Exception:
            continue
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
        if is_job_board_url(target):
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
            return {"application_url": page.url, "resolution_method": "anchor_href"}
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
    return {}


async def captcha_response_state(page: Any) -> Dict[str, Any]:
    """Inspect provider response fields without interacting with the challenge."""
    responses: List[Dict[str, Any]] = []
    for selector in CAPTCHA_RESPONSE_SELECTORS:
        try:
            for element in await page.query_selector_all(selector):
                value = await element.input_value()
                responses.append({
                    "selector": selector,
                    "length": len(value or ""),
                })
        except Exception:
            continue
    return {
        "responses": responses,
        "has_completed_response": any(
            int(item.get("length") or 0) >= 20 for item in responses
        ),
    }


async def _visible_challenge_element(page: Any, selector: str) -> Optional[Dict[str, Any]]:
    try:
        elements = await page.query_selector_all(selector)
    except Exception:
        return None
    for element in elements:
        try:
            if not await element.is_visible():
                continue
            source = str(await element.get_attribute("src") or "").lower()
            class_name = str(await element.get_attribute("class") or "").lower()
            aria_hidden = str(await element.get_attribute("aria-hidden") or "").lower()
            if aria_hidden == "true" or "grecaptcha-badge" in class_name:
                continue
            if "size=invisible" in source or "invisible=true" in source:
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


async def challenge_page_context(page: Any) -> Dict[str, Any]:
    """Collect high-signal visible challenge context without scanning footer copy."""
    try:
        payload = await page.evaluate(
            """() => {
              const visible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return !el.hidden
                  && el.getAttribute('aria-hidden') !== 'true'
                  && style.display !== 'none'
                  && style.visibility !== 'hidden'
                  && Number.parseFloat(style.opacity || '1') > 0.05
                  && rect.width > 0
                  && rect.height > 0;
              };
              const texts = (selector, limit = 12) => Array.from(document.querySelectorAll(selector))
                .filter(visible)
                .slice(0, limit)
                .map((el) => (el.innerText || el.textContent || '').trim())
                .filter(Boolean);
              const controls = Array.from(document.querySelectorAll(
                'input:not([type=hidden]),textarea,select,button,[role=button],[role=combobox]'
              )).filter(visible);
              const applicantControls = controls.filter((el) => /first.?name|last.?name|full.?name|email|phone|resume|résumé|cv|cover.?letter/i.test([
                el.name || '', el.id || '', el.type || '', el.placeholder || '',
                el.getAttribute('aria-label') || ''
              ].join(' '))).length;
              const main = document.querySelector('main,[role=main],form') || document.body;
              return {
                title: document.title || '',
                url: location.href,
                headings: texts('h1,h2,h3,[role=heading]', 10),
                alerts: texts('[role=alert],[aria-live=assertive],[aria-live=polite]', 10),
                dialogs: texts('[role=dialog],[aria-modal=true]', 6),
                mainText: visible(main) ? (main.innerText || '').trim().slice(0, 12000) : '',
                visibleControlCount: controls.length,
                applicantControlCount: applicantControls,
              };
            }"""
        )
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    try:
        title = await page.title()
    except Exception:
        title = ""
    return {
        "title": title,
        "url": str(getattr(page, "url", "") or ""),
        "headings": [],
        "alerts": [],
        "dialogs": [],
        "mainText": "",
        "visibleControlCount": 0,
        "applicantControlCount": 0,
    }


def classify_challenge_context(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Classify only active challenge screens, not incidental job-description text."""
    priority_parts = [
        str(context.get("title") or ""),
        *[str(value) for value in context.get("headings") or []],
        *[str(value) for value in context.get("alerts") or []],
        *[str(value) for value in context.get("dialogs") or []],
    ]
    priority = "\n".join(priority_parts)
    main_text = str(context.get("mainText") or "")
    visible_controls = int(context.get("visibleControlCount") or 0)
    applicant_controls = int(context.get("applicantControlCount") or 0)
    challenge_focused_page = bool(
        applicant_controls == 0
        and visible_controls <= 6
        and len(main_text) <= 12000
    )

    for reason_code, pattern, summary in _BLOCKING_CHALLENGES:
        if pattern.search(priority):
            return {
                "reason_code": reason_code,
                "summary": summary,
                "details": {
                    "matched_text": pattern.pattern,
                    "evidence_source": "title_heading_alert_or_dialog",
                },
            }
        if reason_code != "captcha_detected" and challenge_focused_page and pattern.search(main_text):
            return {
                "reason_code": reason_code,
                "summary": summary,
                "details": {
                    "matched_text": pattern.pattern,
                    "evidence_source": "challenge_focused_main_content",
                },
            }
    return None


async def detect_blocking_challenge(page) -> Optional[Dict[str, Any]]:
    response_state = await captcha_response_state(page)
    captcha_completed = bool(response_state["has_completed_response"])
    if not captcha_completed:
        for selector in _VISIBLE_CAPTCHA_SELECTORS:
            evidence = await _visible_challenge_element(page, selector)
            if evidence:
                return {
                    "reason_code": "captcha_detected",
                    "summary": "A CAPTCHA or human-verification challenge requires manual completion.",
                    "details": evidence,
                }

    context = await challenge_page_context(page)
    challenge = classify_challenge_context(context)
    if challenge and challenge.get("reason_code") == "captcha_detected" and captcha_completed:
        return None
    return challenge


async def find_submit_button(page):
    for selector in SUBMIT_SELECTORS:
        try:
            button = await page.query_selector(selector)
            if button and await button.is_visible() and await button.is_enabled():
                return button
        except Exception:
            pass
    return None
