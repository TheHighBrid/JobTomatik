"""
Playwright-based application form filler.

The browser may fill only:
1. Non-sensitive profile fields with a direct, deterministic mapping.
2. Application questions covered by an active, confirmed answer policy that
   explicitly allows autofill.

Unknown required questions, legal declarations, demographics, and consent
controls are never guessed. They are returned as structured manual-review
items before any submit action occurs.
"""

import asyncio
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from app.services.answer_policy import (
    classify_question,
    resolve_runtime_policy,
    review_reason_for_question,
)


JOB_BOARD_DOMAINS = frozenset([
    "indeed.com", "ca.indeed.com", "www.indeed.com",
    "glassdoor.com", "www.glassdoor.com",
    "linkedin.com", "www.linkedin.com",
    "jobbank.gc.ca", "www.jobbank.gc.ca",
    "guichetemplois.gc.ca", "www.guichetemplois.gc.ca",
    "monster.com", "www.monster.com",
    "ziprecruiter.com", "www.ziprecruiter.com",
    "careerbuilder.com", "www.careerbuilder.com",
    "simplyhired.com", "www.simplyhired.com",
    "eluta.ca", "www.eluta.ca",
    "workopolis.com", "www.workopolis.com",
])

JOB_BOARD_HOSTS = {
    "jobbank.gc.ca", "www.jobbank.gc.ca",
    "guichetemplois.gc.ca", "www.guichetemplois.gc.ca",
}

JOB_BANK_LISTING_PATHS = (
    "/jobsearch/jobposting/",
    "/rechercheemplois/offredemploi/",
)

_FAKE_URL_RE = re.compile(r"/jobs/[0-9a-f]{12,20}/?$", re.IGNORECASE)
_SEARCH_FIELD_NAMES = frozenset([
    "q", "l", "what", "where", "keywords", "location",
    "searchstring", "locationstring", "recherchestring", "localisationstring",
])

APPLY_LINK_HINTS = (
    "apply", "application", "career", "careers", "recruit", "mailto:",
)

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

SAFE_PROFILE_FIELDS: List[Tuple[str, str]] = [
    (r"\bfirst\s*[_\-]?name\b|\bfname\b|given[\s_]name|prenom", "first_name"),
    (r"\blast\s*[_\-]?name\b|\blname\b|surname|family[\s_]name|nom\b", "last_name"),
    (r"\bfull[\s_]name\b|\byour[\s_]name\b|candidate[\s_]name|complete[\s_]name", "full_name"),
    (r"\bemail\b|e[_\-]?mail|courriel", "email"),
    (r"\bphone\b|\bmobile\b|\btelephone\b|\btel\b|\bcell\b|\bphone[\s_]number", "phone"),
    (r"\bcity\b|\bville\b|\bmunicipality\b", "city"),
    (r"\bstate\b|\bprovince\b|\bregion\b|\bprov\b", "state"),
    (r"\bzip\b|\bpostal\b|\bpostcode\b|\bzip[\s_]code\b|\bpostal[\s_]code\b|\bcode\s+postal", "postal_code"),
    (r"\baddress[\s_]?(?:line\s*[12]|1|2)?\b|\bstreet\b|\brue\b", "address"),
    (r"\blinkedin\b", "linkedin_url"),
    (r"\bgithub\b", "github_url"),
    (r"\bportfolio\b|\bwebsite\b|\bpersonal[\s_](?:url|site|web)\b", "portfolio_url"),
    (r"cover\s*letter|lettre\s+de\s+motivation|message\s+to\s+(?:us|employer)", "cover_letter"),
    (r"\bcurrent[\s_](?:role|title|position|employer)\b|\bjob[\s_]title\b|\bposition[\s_]title\b", "current_role"),
    (r"\byears[\s_](?:of[\s_])?experience\b|\bexperience[\s_]years\b", "years_experience"),
]


def _now() -> str:
    return datetime.utcnow().isoformat()


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _first_name(profile: Dict[str, Any]) -> str:
    parts = (profile.get("full_name") or "").split()
    return parts[0] if parts else ""


def _last_name(profile: Dict[str, Any]) -> str:
    parts = (profile.get("full_name") or "").split()
    return " ".join(parts[1:]) if len(parts) > 1 else ""


def _extract_city(address: str) -> str:
    parts = address.split(",")
    return parts[0].strip() if parts else ""


def _extract_province(address: str) -> str:
    parts = address.split(",")
    if len(parts) >= 2:
        tokens = parts[1].strip().split()
        return tokens[0] if tokens else ""
    return ""


def _extract_postal_code(address: str) -> str:
    match = re.search(
        r"\b(?:[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d|\d{5}(?:-\d{4})?)\b",
        address,
        flags=re.IGNORECASE,
    )
    return match.group().upper() if match else ""


def _profile_values(profile: Dict[str, Any], cover_letter: str) -> Dict[str, str]:
    address = profile.get("address") or ""
    profile_data = profile.get("profile_data") or {}
    return {
        "first_name": profile.get("first_name") or _first_name(profile),
        "last_name": profile.get("last_name") or _last_name(profile),
        "full_name": profile.get("full_name") or "",
        "email": profile.get("email") or "",
        "phone": profile.get("phone") or "",
        "city": profile.get("city") or _extract_city(address),
        "state": profile.get("state") or profile.get("province") or _extract_province(address),
        "postal_code": profile.get("postal_code") or _extract_postal_code(address),
        "address": address,
        "linkedin_url": profile.get("linkedin_url") or "",
        "github_url": profile.get("github_url") or "",
        "portfolio_url": profile.get("portfolio_url") or "",
        "cover_letter": cover_letter or "",
        "current_role": profile_data.get("current_role") or profile.get("current_role") or "",
        "years_experience": str(profile_data.get("years_experience") or profile.get("years_experience") or ""),
    }


def _get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _is_fake_url(url: str) -> bool:
    domain = _get_domain(url)
    if domain in {"example.com", "localhost", "127.0.0.1"}:
        return True
    return bool(_FAKE_URL_RE.search(urlparse(url).path))


def _is_job_board_listing(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname in JOB_BOARD_HOSTS and any(fragment in parsed.path for fragment in JOB_BANK_LISTING_PATHS)


def _is_probable_apply_href(href: str, current_url: str) -> bool:
    lowered = href.lower()
    if lowered.startswith("mailto:"):
        return True
    if not any(hint in lowered for hint in APPLY_LINK_HINTS):
        return False
    parsed = urlparse(urljoin(current_url, href))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def _navigate_job_board_listing(page, log: List[Dict[str, Any]]) -> Dict[str, Any]:
    current_url = page.url
    if not _is_job_board_listing(current_url):
        return {}

    log.append({"action": "listing_page_detected", "url": current_url, "ts": _now()})

    for selector in REVEAL_APPLY_SELECTORS:
        try:
            control = await page.query_selector(selector)
            if control:
                await control.click(timeout=5000)
                await page.wait_for_load_state("networkidle", timeout=5000)
                log.append({"action": "apply_instructions_revealed", "selector": selector, "ts": _now()})
                break
        except Exception as exc:
            log.append({
                "action": "apply_reveal_skipped",
                "selector": selector,
                "detail": str(exc)[:160],
                "ts": _now(),
            })

    await page.wait_for_timeout(1000)
    anchors = await page.query_selector_all("a[href]")
    for anchor in anchors:
        href = await anchor.get_attribute("href") or ""
        text = _normalize_text(await anchor.inner_text())
        if not _is_probable_apply_href(href, current_url) and not any(hint in text for hint in APPLY_LINK_HINTS):
            continue

        target = urljoin(current_url, href)
        if target.startswith("mailto:"):
            email = target.removeprefix("mailto:").split("?", 1)[0]
            log.append({"action": "email_apply_detected", "email": email, "ts": _now()})
            return {
                "manual_review_only": True,
                "contact_email": email,
                "reason": "Employer accepts applications by email; review and send manually.",
            }

        if urlparse(target).netloc in JOB_BOARD_HOSTS:
            continue

        log.append({"action": "external_apply_link_found", "url": target, "text": text[:120], "ts": _now()})
        try:
            await page.goto(target, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            log.append({"action": "external_apply_navigated", "url": page.url, "ts": _now()})
            return {"application_url": page.url}
        except Exception as exc:
            log.append({
                "action": "external_apply_navigation_failed",
                "url": target,
                "detail": str(exc)[:200],
                "ts": _now(),
            })
            return {"application_url": target}

    page_text = await page.inner_text("body")
    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", page_text, flags=re.IGNORECASE)
    if email_match:
        email = email_match.group(0)
        log.append({"action": "email_apply_detected", "email": email, "ts": _now()})
        return {
            "manual_review_only": True,
            "contact_email": email,
            "reason": "Employer accepts applications by email; review and send manually.",
        }

    log.append({"action": "apply_target_not_found", "url": current_url, "ts": _now()})
    return {}


def _match_safe_field(descriptor: str) -> Optional[str]:
    for pattern, key in SAFE_PROFILE_FIELDS:
        if re.search(pattern, descriptor, flags=re.IGNORECASE):
            return key
    return None


async def _is_required(element) -> bool:
    required = await element.get_attribute("required")
    aria_required = _normalize_text(await element.get_attribute("aria-required"))
    return required is not None or aria_required == "true"


async def _element_descriptor(page, element) -> str:
    attrs = []
    for attr in ("name", "id", "placeholder", "aria-label", "autocomplete"):
        value = await element.get_attribute(attr)
        if value:
            attrs.append(value)

    element_id = await element.get_attribute("id")
    if element_id:
        label = await page.query_selector(f'label[for="{element_id}"]')
        if label:
            attrs.append(await label.inner_text())

    return _normalize_text(" ".join(attrs))


def _add_review_item(
    review_items: List[Dict[str, Any]],
    *,
    descriptor: str,
    policy_result: Dict[str, Any],
    control_type: str,
    reason_code: Optional[str] = None,
    summary: Optional[str] = None,
) -> None:
    canonical_key = policy_result.get("canonical_key", "custom.unclassified")
    resolved_reason = reason_code or review_reason_for_question(policy_result)
    for item in review_items:
        details = item.get("details", {})
        if (
            item.get("reason_code") == resolved_reason
            and details.get("descriptor") == descriptor
            and details.get("control_type") == control_type
        ):
            return

    review_items.append({
        "reason_code": resolved_reason,
        "summary": summary or f"Approved answer required for: {descriptor or canonical_key}",
        "details": {
            "canonical_key": canonical_key,
            "category": policy_result.get("category"),
            "sensitivity": policy_result.get("sensitivity"),
            "descriptor": descriptor,
            "control_type": control_type,
            "policy_reason": policy_result.get("reason"),
        },
    })


def _option_matches(answer: str, label: str, value: str) -> bool:
    normalized_answer = _normalize_text(answer)
    normalized_label = _normalize_text(label)
    normalized_value = _normalize_text(value)
    if not normalized_answer:
        return False
    return (
        normalized_answer == normalized_label
        or normalized_answer == normalized_value
        or normalized_answer in normalized_label
        or normalized_label in normalized_answer
    )


async def _fill_select_fields(
    page,
    policies: List[Dict[str, Any]],
    log: List[Dict[str, Any]],
    review_items: List[Dict[str, Any]],
) -> int:
    filled = 0
    for select in await page.query_selector_all("select"):
        try:
            descriptor = await _element_descriptor(page, select)
            policy_result = resolve_runtime_policy(descriptor, policies)
            required = await _is_required(select)

            if not policy_result.get("can_autofill"):
                if required:
                    _add_review_item(
                        review_items,
                        descriptor=descriptor,
                        policy_result=policy_result,
                        control_type="select",
                    )
                log.append({
                    "action": "select_policy_missing",
                    "descriptor": descriptor[:160],
                    "required": required,
                    "canonical_key": policy_result.get("canonical_key"),
                    "ts": _now(),
                })
                continue

            answer = str(policy_result.get("answer") or "")
            selected_value = None
            for option in await select.query_selector_all("option"):
                value = await option.get_attribute("value") or ""
                label = await option.inner_text()
                disabled = await option.get_attribute("disabled")
                if disabled is not None or not value:
                    continue
                if _option_matches(answer, label, value):
                    selected_value = value
                    break

            if not selected_value:
                _add_review_item(
                    review_items,
                    descriptor=descriptor,
                    policy_result=policy_result,
                    control_type="select",
                    reason_code="unsupported_control",
                    summary=f"Approved answer does not match any available option: {descriptor}",
                )
                log.append({
                    "action": "select_answer_not_found",
                    "descriptor": descriptor[:160],
                    "canonical_key": policy_result.get("canonical_key"),
                    "ts": _now(),
                })
                continue

            await select.select_option(value=selected_value)
            filled += 1
            log.append({
                "action": "select",
                "descriptor": descriptor[:160],
                "canonical_key": policy_result.get("canonical_key"),
                "ts": _now(),
            })
        except Exception as exc:
            log.append({"action": "select_skipped", "detail": str(exc)[:200], "ts": _now()})
    return filled


async def _fill_choice_fields(
    page,
    policies: List[Dict[str, Any]],
    log: List[Dict[str, Any]],
    review_items: List[Dict[str, Any]],
) -> int:
    filled = 0
    groups = await page.query_selector_all("fieldset, [role='radiogroup']")
    for group in groups:
        try:
            descriptor = _normalize_text(await group.inner_text())
            choices = await group.query_selector_all("input[type='radio'], input[type='checkbox']")
            required = any([await _is_required(choice) for choice in choices]) if choices else False
            policy_result = resolve_runtime_policy(descriptor, policies)

            if not policy_result.get("can_autofill"):
                if required:
                    _add_review_item(
                        review_items,
                        descriptor=descriptor,
                        policy_result=policy_result,
                        control_type="choice_group",
                    )
                log.append({
                    "action": "choice_policy_missing",
                    "descriptor": descriptor[:160],
                    "required": required,
                    "canonical_key": policy_result.get("canonical_key"),
                    "ts": _now(),
                })
                continue

            answer = str(policy_result.get("answer") or "")
            matched = False
            for choice in choices:
                choice_descriptor = await _element_descriptor(page, choice)
                if not choice_descriptor:
                    choice_descriptor = _normalize_text(
                        await choice.evaluate("el => el.closest('label')?.innerText || ''")
                    )
                value = await choice.get_attribute("value") or ""
                if not _option_matches(answer, choice_descriptor, value):
                    continue
                if not await choice.is_checked():
                    await choice.check()
                filled += 1
                matched = True
                log.append({
                    "action": "choice",
                    "descriptor": descriptor[:160],
                    "canonical_key": policy_result.get("canonical_key"),
                    "ts": _now(),
                })
                break

            if not matched:
                _add_review_item(
                    review_items,
                    descriptor=descriptor,
                    policy_result=policy_result,
                    control_type="choice_group",
                    reason_code="unsupported_control",
                    summary=f"Approved answer does not match any available choice: {descriptor}",
                )
        except Exception as exc:
            log.append({"action": "choice_skipped", "detail": str(exc)[:200], "ts": _now()})
    return filled


async def _fill_common_fields(
    page,
    profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    log: List[Dict[str, Any]],
) -> Dict[str, Any]:
    values = _profile_values(profile, cover_letter)
    policies = list(profile.get("answer_policies") or [])
    review_items: List[Dict[str, Any]] = []
    filled = 0

    elements = await page.query_selector_all("input:not([type=hidden]), textarea")
    for element in elements:
        try:
            input_type = _normalize_text(await element.get_attribute("type"))
            if input_type in {"hidden", "submit", "button", "reset", "checkbox", "radio", "file"}:
                continue

            descriptor = await _element_descriptor(page, element)
            name = _normalize_text(await element.get_attribute("name"))
            if name in _SEARCH_FIELD_NAMES:
                continue

            safe_field = _match_safe_field(descriptor)
            if safe_field:
                value = values.get(safe_field, "")
                if value:
                    await element.fill(str(value))
                    filled += 1
                    log.append({
                        "action": "fill",
                        "field": safe_field,
                        "descriptor": descriptor[:160],
                        "source": "profile",
                        "ts": _now(),
                    })
                elif await _is_required(element):
                    policy_result = classify_question(descriptor)
                    _add_review_item(
                        review_items,
                        descriptor=descriptor,
                        policy_result=policy_result,
                        control_type="text",
                        reason_code="ambiguous_question",
                        summary=f"Required profile value is missing: {descriptor or safe_field}",
                    )
                continue

            policy_result = resolve_runtime_policy(descriptor, policies)
            if policy_result.get("can_autofill"):
                await element.fill(str(policy_result.get("answer") or ""))
                filled += 1
                log.append({
                    "action": "fill",
                    "descriptor": descriptor[:160],
                    "canonical_key": policy_result.get("canonical_key"),
                    "source": "answer_policy",
                    "ts": _now(),
                })
            elif await _is_required(element):
                _add_review_item(
                    review_items,
                    descriptor=descriptor,
                    policy_result=policy_result,
                    control_type="text",
                )
        except Exception as exc:
            log.append({"action": "fill_skipped", "detail": str(exc)[:200], "ts": _now()})

    filled += await _fill_select_fields(page, policies, log, review_items)
    filled += await _fill_choice_fields(page, policies, log, review_items)

    if resume_path and os.path.exists(resume_path):
        for file_input in await page.query_selector_all('input[type="file"]'):
            try:
                await file_input.set_input_files(resume_path)
                filled += 1
                log.append({"action": "upload_resume", "ts": _now()})
                break
            except Exception as exc:
                log.append({"action": "upload_resume_skipped", "detail": str(exc)[:200], "ts": _now()})
    elif resume_path:
        log.append({"action": "upload_resume_skipped", "detail": "resume path not found", "ts": _now()})

    return {"filled_count": filled, "review_items": review_items}


async def _find_submit_button(page):
    for selector in SUBMIT_SELECTORS:
        try:
            button = await page.query_selector(selector)
            if button:
                return button
        except Exception:
            pass
    return None


async def fill_and_submit_application(
    job_url: str,
    user_profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    log: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "success": False,
        "dry_run": dry_run,
        "url": job_url,
        "log": log,
        "submitted_at": None,
        "error": None,
        "fields_filled": 0,
        "requires_manual_review": False,
        "review_items": [],
    }

    if not _is_allowed_url(job_url):
        result["error"] = "Invalid or unsupported job URL"
        result["requires_manual_review"] = True
        log.append({"action": "error", "detail": result["error"], "ts": _now()})
        return result

    if _is_fake_url(job_url):
        result["error"] = "Placeholder URL; manual application required"
        result["requires_manual_review"] = True
        log.append({"action": "fake_url_skipped", "url": job_url, "ts": _now()})
        return result

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
            )

            page = await context.new_page()
            log.append({"action": "navigate", "url": job_url, "ts": _now()})
            try:
                await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeoutError:
                log.append({"action": "navigation_timeout", "ts": _now()})

            await asyncio.sleep(1.5)
            handoff = await _navigate_job_board_listing(page, log)
            if handoff.get("application_url"):
                result["application_url"] = handoff["application_url"]
            if handoff.get("contact_email"):
                result["contact_email"] = handoff["contact_email"]
            if handoff.get("manual_review_only"):
                result["requires_manual_review"] = True
                result["success"] = bool(dry_run)
                result["error"] = handoff.get("reason")
                await browser.close()
                return result

            outcome = await _fill_common_fields(page, user_profile, cover_letter, resume_path, log)
            result["fields_filled"] = outcome["filled_count"]
            result["review_items"] = outcome["review_items"]

            if outcome["review_items"]:
                result["requires_manual_review"] = True
                result["error"] = "Required application questions need approved answer policies."
                result["success"] = bool(dry_run)
                log.append({
                    "action": "answer_policy_review_required",
                    "count": len(outcome["review_items"]),
                    "ts": _now(),
                })
            elif dry_run:
                result["success"] = True
                log.append({
                    "action": "dry_run_complete",
                    "fields_filled": result["fields_filled"],
                    "ts": _now(),
                })
            elif result["fields_filled"] >= 1:
                submit_button = await _find_submit_button(page)
                if submit_button:
                    log.append({"action": "submit_click", "ts": _now()})
                    await submit_button.click()
                    await asyncio.sleep(3)
                    result["submitted_at"] = _now()
                    result["success"] = True
                    log.append({"action": "submit_clicked", "status": "unconfirmed", "ts": _now()})
                else:
                    result["error"] = "Form filled but no submit button found; manual submit required."
                    result["requires_manual_review"] = True
                    log.append({
                        "action": "no_submit_button",
                        "fields_filled": result["fields_filled"],
                        "ts": _now(),
                    })
            else:
                result["error"] = "No application form fields found; manual apply required."
                result["requires_manual_review"] = True
                log.append({"action": "no_fields_found", "url": page.url, "ts": _now()})

            await browser.close()

    except ImportError:
        result["error"] = "Playwright not installed"
        result["requires_manual_review"] = True
        log.append({"action": "playwright_unavailable", "ts": _now()})
    except Exception as exc:
        result["error"] = str(exc)
        result["requires_manual_review"] = True
        log.append({"action": "error", "detail": str(exc)[:300], "ts": _now()})

    return result


def _is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
