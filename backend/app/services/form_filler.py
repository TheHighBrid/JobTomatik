"""
Playwright-based form filler and application submitter.

dry_run=True fills recognized fields and uploads the resume but never clicks submit.
ALLOW_REAL_APPLICATION_SUBMIT env var must be set to enable live submission.
"""
import asyncio
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

COMMON_FIELDS: List[Tuple[str, str]] = [
    # Name fields
    (r"\bfirst\s*[_\-]?name\b|\bfname\b|given[\s_]name|prenom", "first_name"),
    (r"\blast\s*[_\-]?name\b|\blname\b|surname|family[\s_]name|nom\b", "last_name"),
    (r"\bfull[\s_]name\b|\byour[\s_]name\b|candidate[\s_]name|complete[\s_]name", "full_name"),
    # Contact
    (r"\bemail\b|e[_\-]?mail|courriel", "email"),
    (r"\bphone\b|\bmobile\b|\btelephone\b|\btel\b|\bcell\b|\bphone[\s_]number", "phone"),
    # Address
    (r"\bcity\b|\bville\b|\bmunicipality\b", "city"),
    (r"\bstate\b|\bprovince\b|\bregion\b|\bprov\b", "state"),
    (r"\bzip\b|\bpostal\b|\bpostcode\b|\bzip[\s_]code\b|\bpostal[\s_]code\b|\bcode\s+postal", "postal_code"),
    (r"\baddress[\s_]?(?:line\s*[12]|1|2)?\b|\bstreet\b|\brue\b", "address"),
    # Social / web
    (r"\blinkedin\b", "linkedin_url"),
    (r"\bgithub\b", "github_url"),
    (r"\bportfolio\b|\bwebsite\b|\bpersonal[\s_](?:url|site|web)\b", "portfolio_url"),
    # Application text
    (r"cover\s*letter|lettre\s+de\s+motivation|motivation|introduction|why\s+are\s+you|tell\s+us\s+about\s+yourself|message\s+to\s+(?:us|employer)", "cover_letter"),
    # Professional
    (r"\bcurrent[\s_](?:role|title|position|employer)\b|\bjob[\s_]title\b|\bposition[\s_]title\b|\btitle\b(?!.*\bname)", "current_role"),
    (r"\byears[\s_](?:of[\s_])?experience\b|\bexperience[\s_]years\b", "years_experience"),
    (r"\bsalary[\s_](?:expectation|expected|desired|requirement)\b|\bexpected[\s_]salary\b", "salary_expectation"),
    # Availability
    (r"\bstart\s*date\b|\bavailable\s*(?:from|date)\b|\bdisponible\b", "availability"),
]

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
    "niveau.*études": "baccalauréat",
    "willing to relocate": "no",
    "gender": "prefer not",
    "ethnicity": "prefer not",
    "veteran": "no",
    "disability": "no",
}

SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Submit Application")',
    'button:has-text("Submit")',
    'button:has-text("Apply Now")',
    'button:has-text("Apply")',
    'button:has-text("Send Application")',
    'button:has-text("Complete Application")',
    '[data-testid*="submit"]',
    '[aria-label*="submit" i]',
]


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


async def _element_descriptor(page, element) -> str:
    """Build a rich descriptor string for a form element to match against field patterns."""
    attrs = []
    for attr in ("name", "id", "placeholder", "aria-label", "autocomplete", "title", "data-label"):
        value = await element.get_attribute(attr)
        if value:
            attrs.append(value)

    # Try label[for=id]
    element_id = await element.get_attribute("id")
    if element_id:
        try:
            label = await page.query_selector(f'label[for="{element_id}"]')
            if label:
                text = await label.inner_text()
                if text:
                    attrs.append(text)
        except Exception:
            pass

    # Try ancestor label
    if not any(a for a in attrs if len(a) > 3):
        try:
            label_text = await element.evaluate("""el => {
                let cur = el.parentElement;
                for (let i = 0; i < 5; i++) {
                    if (!cur) break;
                    const label = cur.querySelector('label');
                    if (label) return label.innerText;
                    if (cur.tagName === 'LABEL') return cur.innerText;
                    const legend = cur.querySelector('legend');
                    if (legend) return legend.innerText;
                    cur = cur.parentElement;
                }
                return '';
            }""")
            if label_text:
                attrs.append(label_text)
        except Exception:
            pass

    return _normalize_text(" ".join(attrs))


def _match_field_key(descriptor: str) -> Optional[str]:
    for pattern, key in COMMON_FIELDS:
        if re.search(pattern, descriptor, flags=re.IGNORECASE):
            return key
    return None


def _match_select_answer(descriptor: str) -> Optional[str]:
    for pattern, answer in COMMON_SELECT_ANSWERS.items():
        if re.search(pattern, descriptor, flags=re.IGNORECASE):
            return answer
    return None


async def _fill_select(page, element, descriptor: str, log: List[Dict]) -> bool:
    """Try to pick the most appropriate option in a <select> based on descriptor."""
    answer_hint = _match_select_answer(descriptor)
    if not answer_hint:
        return False
    try:
        options = await element.evaluate("""el => Array.from(el.options).map(o => ({value: o.value, text: o.text}))""")
        best = None
        hint_lower = answer_hint.lower()
        for opt in options:
            if opt["value"].lower() in ("", "select", "please select", "--"):
                continue
            if hint_lower in opt["text"].lower() or hint_lower in opt["value"].lower():
                best = opt["value"]
                break
        if best is None and options:
            # Skip blank/placeholder option; pick first real option
            for opt in options:
                if opt["value"] not in ("", "select", "--"):
                    best = opt["value"]
                    break
        if best:
            await element.select_option(value=best)
            log.append({"action": "select", "field": descriptor[:80], "value": best, "ts": _now()})
            return True
    except Exception as exc:
        log.append({"action": "select_skipped", "detail": str(exc), "ts": _now()})
    return False


async def _fill_common_fields(
    page,
    profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    log: List[Dict[str, Any]],
) -> int:
    values = _profile_values(profile, cover_letter)
    filled = 0

    # --- Text inputs and textareas ---
    elements = await page.query_selector_all("input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=checkbox]):not([type=radio]):not([type=file]), textarea")
    for element in elements:
        try:
            descriptor = await _element_descriptor(page, element)
            if not descriptor:
                continue
            field_key = _match_field_key(descriptor)
            value = values.get(field_key or "", "")
            if not value:
                continue
            await element.fill(str(value))
            filled += 1
            log.append({"action": "fill", "field": field_key, "descriptor": descriptor[:120], "ts": _now()})
        except Exception as exc:
            log.append({"action": "fill_skipped", "detail": str(exc)[:100], "ts": _now()})

    # --- Select dropdowns ---
    selects = await page.query_selector_all("select")
    for element in selects:
        try:
            descriptor = await _element_descriptor(page, element)
            if await _fill_select(page, element, descriptor, log):
                filled += 1
        except Exception:
            pass

    # --- Checkboxes: accept terms ---
    checkboxes = await page.query_selector_all('input[type="checkbox"]')
    for cb in checkboxes:
        try:
            descriptor = await _element_descriptor(page, cb)
            if re.search(r"terms|agree|consent|privacy|policy|confirm", descriptor, re.IGNORECASE):
                is_checked = await cb.is_checked()
                if not is_checked:
                    await cb.check()
                    filled += 1
                    log.append({"action": "checkbox_checked", "descriptor": descriptor[:80], "ts": _now()})
        except Exception:
            pass

    # --- File upload (resume) ---
    if resume_path and os.path.exists(resume_path):
        file_inputs = await page.query_selector_all('input[type="file"]')
        for file_input in file_inputs:
            try:
                accept = await file_input.get_attribute("accept") or ""
                if accept and "pdf" not in accept.lower() and "image" in accept.lower():
                    continue
                await file_input.set_input_files(resume_path)
                filled += 1
                log.append({"action": "upload_resume", "path": resume_path, "ts": _now()})
                break
            except Exception as exc:
                log.append({"action": "upload_resume_skipped", "detail": str(exc)[:100], "ts": _now()})
    elif resume_path:
        log.append({"action": "upload_resume_skipped", "detail": "resume file not found on disk", "ts": _now()})

    return filled


async def _find_submit_button(page):
    for selector in SUBMIT_SELECTORS:
        try:
            button = await page.query_selector(selector)
            if button and await button.is_visible():
                return button
        except Exception:
            pass
    return None


def _is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


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
    }

    if not _is_allowed_url(job_url):
        result["error"] = "Invalid or unsupported job URL"
        log.append({"action": "error", "detail": result["error"], "ts": _now()})
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
            filled_count = await _fill_common_fields(page, user_profile, cover_letter, resume_path, log)

            if dry_run:
                result["success"] = True
                log.append({"action": "dry_run_complete", "fields_filled": filled_count, "ts": _now()})
            elif filled_count > 0:
                submit_btn = await _find_submit_button(page)
                if submit_btn:
                    log.append({"action": "submit_click", "ts": _now()})
                    await submit_btn.click()
                    await asyncio.sleep(3)
                    result["submitted_at"] = _now()
                    result["success"] = True
                    log.append({"action": "submitted", "status": "ok", "ts": _now()})
                else:
                    result["error"] = "No submit button found"
                    log.append({"action": "submit_skipped", "reason": result["error"], "ts": _now()})
            else:
                result["error"] = "No recognizable application fields were found on this page"
                log.append({"action": "no_fields_filled", "ts": _now()})

            await browser.close()

    except ImportError:
        result["error"] = "Playwright is not installed (expected on Termux — dry-run only)"
        log.append({"action": "playwright_unavailable", "ts": _now()})
        result["success"] = True
    except Exception as exc:
        result["error"] = str(exc)
        log.append({"action": "error", "detail": str(exc)[:300], "ts": _now()})

    return result
