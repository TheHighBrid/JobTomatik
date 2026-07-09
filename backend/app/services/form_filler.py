"""
Playwright-based form filler and application submitter.

Flow:
1. Navigate to the stored job URL (may be a listing page or direct apply URL).
2. If we land on a job-board listing page, look for an Apply button and click it.
   Some sites navigate in the same tab; others open a new tab — both are handled.
3. Fill all recognised text/textarea fields with profile data.
4. Answer common select/dropdown fields (work auth, education, etc.).
5. Upload the resume to any file input found.
6. Click the submit button if any meaningful application fields were filled.
"""

import asyncio
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

# ── domain sets ──────────────────────────────────────────────────────────────

# These are job-board listing domains; we need to click Apply before filling.
JOB_BOARD_DOMAINS = frozenset([
    "indeed.com", "ca.indeed.com", "www.indeed.com",
    "glassdoor.com", "www.glassdoor.com",
    "linkedin.com", "www.linkedin.com",
    # Job Bank Canada (English and French versions)
    "jobbank.gc.ca", "www.jobbank.gc.ca",
    "guichetemplois.gc.ca", "www.guichetemplois.gc.ca",
    "monster.com", "www.monster.com",
    "ziprecruiter.com", "www.ziprecruiter.com",
    "careerbuilder.com", "www.careerbuilder.com",
    "simplyhired.com", "www.simplyhired.com",
    "eluta.ca", "www.eluta.ca",
    "workopolis.com", "www.workopolis.com",
])

# URLs that look like fake/placeholder job URLs (old mock-generator artefact).
_FAKE_URL_RE = re.compile(r"/jobs/[0-9a-f]{12,20}/?$", re.IGNORECASE)

# Field names used by job-board search bars — skip these even if the regex matches.
_SEARCH_FIELD_NAMES = frozenset([
    "q", "l", "what", "where", "keywords", "location",
    # Job Bank Canada search bar field names (English + French)
    "searchstring", "locationstring", "recherchestring", "localisationstring",
])

# ── selector lists ────────────────────────────────────────────────────────────

APPLY_BUTTON_SELECTORS = [
    # Indeed
    'button[data-testid="apply-button"]',
    '.indeed-apply-button',
    '.icl-Button--primary',
    # LinkedIn
    '.jobs-apply-button',
    '[data-control-name*="apply" i]',
    # Generic
    'a[href*="/apply" i]:not([href*="applied" i])',
    '[data-testid*="apply" i]:not([data-testid*="applied" i])',
    '[aria-label*="apply" i]:not([aria-label*="applied" i])',
]

APPLY_BUTTON_TEXT_PATTERNS = [
    r"easy\s+apply",
    r"apply\s+now",
    r"apply\s+for\s+this\s+job",
    r"apply\s+on\s+company\s+website",
    r"apply\s+with",
    r"apply\s+to\s+this",
    r"postuler\s+maintenant",
    r"postuler",
    r"how\s+to\s+apply",
    r"comment\s+postuler",
    r"^apply$",
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

COMMON_FIELDS: List[Tuple[str, str]] = [
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
    (r"cover\s*letter|lettre\s+de\s+motivation|motivation|introduction|why\s+are\s+you|tell\s+us\s+about\s+yourself|message\s+to\s+(?:us|employer)", "cover_letter"),
    (r"\bcurrent[\s_](?:role|title|position|employer)\b|\bjob[\s_]title\b|\bposition[\s_]title\b|\btitle\b(?!.*\bname)", "current_role"),
    (r"\byears[\s_](?:of[\s_])?experience\b|\bexperience[\s_]years\b", "years_experience"),
    (r"\bsalary[\s_](?:expectation|expected|desired|requirement)\b|\bexpected[\s_]salary\b", "salary_expectation"),
    (r"\bstart\s*date\b|\bavailable\s*(?:from|date)\b|\bdisponible\b", "availability"),
]

# Select/dropdown answers keyed by lowercased question text (partial match).
COMMON_SELECT_ANSWERS: Dict[str, str] = {
    "work authorization": "yes",
    "authorized to work": "yes",
    "legally authorized": "yes",
    "require sponsorship": "no",
    "visa sponsorship": "no",
    "currently employed": "yes",
    "how did you hear": "job board",
    "highest education": "bachelor",
    "highest degree": "bachelor",
    "willing to relocate": "no",
    "gender": "prefer not",
    "ethnicity": "prefer not",
    "veteran": "no",
    "disability": "no",
    "disability status": "no",
    "protected veteran": "no",
}


# ── helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat()


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


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _profile_values(profile: Dict[str, Any], cover_letter: str) -> Dict[str, str]:
    address = profile.get("address") or ""
    prefs = profile.get("profile_data") or {}
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
        "current_role": prefs.get("current_role") or profile.get("current_role") or "",
        "years_experience": str(prefs.get("years_experience") or profile.get("years_experience") or ""),
        "salary_expectation": str(profile.get("min_salary") or ""),
        "availability": "Immediately",
    }


def _get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _is_job_board(url: str) -> bool:
    domain = _get_domain(url)
    return any(domain == bd or domain.endswith("." + bd) for bd in JOB_BOARD_DOMAINS)


def _is_fake_url(url: str) -> bool:
    """Detect old hex-hash placeholder URLs that don't point to real job pages."""
    domain = _get_domain(url)
    if domain in {"example.com", "localhost", "127.0.0.1"}:
        return True
    return bool(_FAKE_URL_RE.search(urlparse(url).path))


JOB_BOARD_HOSTS = {"jobbank.gc.ca", "www.jobbank.gc.ca"}

APPLY_LINK_HINTS = (
    "apply",
    "application",
    "career",
    "careers",
    "recruit",
    "mailto:",
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


def _is_job_board_listing(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.hostname in JOB_BOARD_HOSTS and "/jobsearch/jobposting/" in parsed.path


def _is_probable_apply_href(href: str, current_url: str) -> bool:
    lowered = href.lower()
    if lowered.startswith("mailto:"):
        return True
    if not any(hint in lowered for hint in APPLY_LINK_HINTS):
        return False
    parsed = urlparse(urljoin(current_url, href))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def _navigate_job_board_listing(page, log: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Move from an aggregator listing, such as Job Bank, to the real apply target.

    Job Bank search results store the employer's instructions behind a
    "Show how to apply" section. Treating that page itself as the application
    form leaves the automation stuck on the listing.
    """
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
            log.append({"action": "apply_reveal_skipped", "selector": selector, "detail": str(exc)[:160], "ts": _now()})

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
            await page.wait_for_load_state("networkidle", timeout=10000)
            log.append({"action": "external_apply_navigated", "url": page.url, "ts": _now()})
            return {"application_url": page.url}
        except Exception as exc:
            log.append({"action": "external_apply_navigation_failed", "url": target, "detail": str(exc)[:200], "ts": _now()})
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
    }

    if not _is_allowed_url(job_url):
        result["error"] = "Invalid or unsupported job URL"
        log.append({"action": "error", "detail": result["error"], "ts": _now()})
        return result

    # Old hex-hash placeholder URLs can't be applied to — mark for manual review.
    if _is_fake_url(job_url):
        result["error"] = "Placeholder URL — manual application required"
        result["requires_manual_review"] = True
        log.append({"action": "fake_url_skipped", "url": job_url, "ts": _now()})
        return result

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(
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
                if dry_run:
                    result["success"] = True
                    result["error"] = handoff.get("reason")
                    log.append({"action": "dry_run_complete", "fields_filled": 0, "ts": _now()})
                else:
                    result["error"] = handoff.get("reason")
                await browser.close()
                return result

            filled_count = await _fill_common_fields(page, user_profile, cover_letter, resume_path, log)
            result["fields_filled"] = filled_count
            result["requires_manual_review"] = filled_count == 0

            if dry_run:
                result["success"] = True
                log.append({"action": "dry_run_complete", "fields_filled": filled_count, "ts": _now()})
            elif filled_count >= 1:
                submit_btn = await _find_submit_button(form_page)
                if submit_btn:
                    log.append({"action": "submit_click", "ts": _now()})
                    await submit_btn.click()
                    await asyncio.sleep(3)
                    result["submitted_at"] = _now()
                    result["success"] = True
                    result["requires_manual_review"] = False
                    log.append({"action": "submitted", "status": "ok", "ts": _now()})
                else:
                    result["error"] = "Form filled but no submit button found — manual submit required"
                    result["requires_manual_review"] = True
                    log.append({"action": "no_submit_button", "fields_filled": filled_count, "ts": _now()})
            else:
                result["error"] = "No application form fields found — manual apply required"
                result["requires_manual_review"] = True
                log.append({"action": "no_fields_found", "url": form_page.url, "ts": _now()})

            await browser.close()

    except ImportError:
        result["error"] = "Playwright not installed"
        log.append({"action": "playwright_unavailable", "ts": _now()})
        result["success"] = True
    except Exception as exc:
        result["error"] = str(exc)
        log.append({"action": "error", "detail": str(exc)[:300], "ts": _now()})

    return result


async def _fill_common_fields(
    page,
    profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    log: List[Dict[str, Any]],
) -> int:
    values = _profile_values(profile, cover_letter)
    elements = await page.query_selector_all("input:not([type=hidden]), textarea")
    filled = 0

    for element in elements:
        try:
            input_type = _normalize_text(await element.get_attribute("type"))
            if input_type in {"hidden", "submit", "button", "reset", "checkbox", "radio", "file"}:
                continue

            descriptor = await _element_descriptor(page, element)
            field_key = _match_field_key(descriptor)
            value = values.get(field_key or "", "")
            if not value:
                continue

            await element.fill(str(value))
            filled += 1
            log.append({"action": "fill", "field": field_key, "descriptor": descriptor[:120], "ts": _now()})
        except Exception as exc:
            log.append({"action": "fill_skipped", "detail": str(exc), "ts": _now()})

    filled += await _fill_select_fields(page, log)
    filled += await _fill_choice_fields(page, log)

    if resume_path and os.path.exists(resume_path):
        file_inputs = await page.query_selector_all('input[type="file"]')
        for file_input in file_inputs:
            try:
                await file_input.set_input_files(resume_path)
                filled += 1
                log.append({"action": "upload_resume", "path": resume_path, "ts": _now()})
                break
            except Exception as exc:
                log.append({"action": "upload_resume_skipped", "detail": str(exc), "ts": _now()})
    elif resume_path:
        log.append({"action": "upload_resume_skipped", "detail": "resume path not found", "ts": _now()})

    return filled


async def _fill_select_fields(page, log: List[Dict[str, Any]]) -> int:
    filled = 0
    selects = await page.query_selector_all("select")
    for select in selects:
        try:
            descriptor = await _element_descriptor(page, select)
            answer_hint = _select_answer_hint(descriptor)
            options = await select.query_selector_all("option")
            selected_value = None
            fallback_value = None

            for option in options:
                value = await option.get_attribute("value")
                label = _normalize_text(await option.inner_text())
                disabled = await option.get_attribute("disabled")
                if disabled is not None or not value:
                    continue
                if not fallback_value and not _is_placeholder_option(label):
                    fallback_value = value
                if answer_hint and answer_hint in label:
                    selected_value = value
                    break

            selected_value = selected_value or fallback_value
            if not selected_value:
                continue

            await select.select_option(value=selected_value)
            filled += 1
            log.append({"action": "select", "descriptor": descriptor[:120], "value": selected_value, "ts": _now()})
        except Exception as exc:
            log.append({"action": "select_skipped", "detail": str(exc), "ts": _now()})
    return filled


def _select_answer_hint(descriptor: str) -> Optional[str]:
    for pattern, answer in COMMON_SELECT_ANSWERS.items():
        if re.search(pattern, descriptor, flags=re.IGNORECASE):
            return answer
    return None


def _is_placeholder_option(label: str) -> bool:
    return not label or any(token in label for token in ("select", "choose", "please", "--"))


async def _fill_choice_fields(page, log: List[Dict[str, Any]]) -> int:
    filled = 0
    groups = await page.query_selector_all("fieldset, [role='radiogroup']")
    for group in groups:
        try:
            descriptor = _normalize_text(await group.inner_text())
            answer_hint = _select_answer_hint(descriptor)
            if not answer_hint:
                continue

            choices = await group.query_selector_all("input[type='radio'], input[type='checkbox']")
            for choice in choices:
                choice_descriptor = await _element_descriptor(page, choice)
                choice_text = choice_descriptor or _normalize_text(await choice.evaluate("el => el.closest('label')?.innerText || ''"))
                if answer_hint not in choice_text:
                    continue
                checked = await choice.is_checked()
                if not checked:
                    await choice.check()
                filled += 1
                log.append({"action": "choice", "descriptor": descriptor[:120], "value": answer_hint, "ts": _now()})
                break
        except Exception as exc:
            log.append({"action": "choice_skipped", "detail": str(exc), "ts": _now()})
    return filled


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


def _match_field_key(descriptor: str) -> Optional[str]:
    for pattern, key in COMMON_FIELDS:
        if re.search(pattern, descriptor, flags=re.IGNORECASE):
            return key
    return None


async def _find_submit_button(page):
    for selector in SUBMIT_SELECTORS:
        try:
            button = await page.query_selector(selector)
            if button:
                return button
        except Exception:
            pass
    return None


def _is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
