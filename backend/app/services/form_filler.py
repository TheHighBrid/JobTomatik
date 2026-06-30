"""
Playwright-based form filler and application submitter.

The filler intentionally supports a conservative dry-run mode. Dry-run mode fills
recognized fields and uploads the resume, but never clicks a submit button.
"""
import asyncio
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

COMMON_FIELDS: List[Tuple[str, str]] = [
    (r"\bfirst\s*name\b|\bfname\b|given\s*name", "first_name"),
    (r"\blast\s*name\b|\blname\b|surname|family\s*name", "last_name"),
    (r"\bfull\s*name\b|\byour\s*name\b|candidate\s*name", "full_name"),
    (r"email|e-mail", "email"),
    (r"phone|mobile|telephone|tel\b", "phone"),
    (r"\bcity\b", "city"),
    (r"state|province|region", "state"),
    (r"zip|postal|postcode", "postal_code"),
    (r"address|street", "address"),
    (r"linkedin", "linkedin_url"),
    (r"github", "github_url"),
    (r"portfolio|website|personal\s*url|personal\s*site", "portfolio_url"),
    (r"cover\s*letter|motivation|introduction|why\s+are\s+you\s+interested", "cover_letter"),
]

SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Submit")',
    'button:has-text("Apply")',
    'button:has-text("Send Application")',
    'button:has-text("Submit Application")',
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


def _extract_state(address: str) -> str:
    parts = address.split(",")
    if len(parts) >= 2:
        state_zip = parts[1].strip().split()
        return state_zip[0] if state_zip else ""
    return ""


def _extract_postal_code(address: str) -> str:
    # Supports US ZIP and Canadian postal codes.
    match = re.search(
        r"\b(?:\d{5}(?:-\d{4})?|[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d)\b",
        address,
        flags=re.IGNORECASE,
    )
    return match.group().upper() if match else ""


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _profile_values(profile: Dict[str, Any], cover_letter: str) -> Dict[str, str]:
    address = profile.get("address") or ""
    return {
        "first_name": profile.get("first_name") or _first_name(profile),
        "last_name": profile.get("last_name") or _last_name(profile),
        "full_name": profile.get("full_name") or "",
        "email": profile.get("email") or "",
        "phone": profile.get("phone") or "",
        "city": profile.get("city") or _extract_city(address),
        "state": profile.get("state") or profile.get("province") or _extract_state(address),
        "postal_code": profile.get("postal_code") or profile.get("zip") or _extract_postal_code(address),
        "address": address,
        "linkedin_url": profile.get("linkedin_url") or "",
        "github_url": profile.get("github_url") or "",
        "portfolio_url": profile.get("portfolio_url") or "",
        "cover_letter": cover_letter or "",
    }


async def fill_and_submit_application(
    job_url: str,
    user_profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Navigate to a job application form, fill recognized fields, attach a resume,
    and optionally submit.

    dry_run=True means fields are filled but the submit button is not clicked.
    """
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

            await asyncio.sleep(1)
            filled_count = await _fill_common_fields(page, user_profile, cover_letter, resume_path, log)

            if dry_run:
                result["success"] = True
                log.append({"action": "dry_run_complete", "fields_filled": filled_count, "ts": _now()})
            elif filled_count > 0:
                submit_btn = await _find_submit_button(page)
                if submit_btn:
                    log.append({"action": "submit", "ts": _now()})
                    await submit_btn.click()
                    await asyncio.sleep(3)
                    result["submitted_at"] = _now()
                    result["success"] = True
                    log.append({"action": "submitted", "status": "ok", "ts": _now()})
                else:
                    result["error"] = "No submit button found"
                    log.append({"action": "submit_skipped", "reason": result["error"], "ts": _now()})
            else:
                result["error"] = "No recognizable application fields were found"
                log.append({"action": "no_fields_filled", "ts": _now()})

            await browser.close()

    except ImportError:
        result["error"] = "Playwright is not installed"
        log.append({"action": "error", "detail": result["error"], "ts": _now()})
    except Exception as exc:
        result["error"] = str(exc)
        log.append({"action": "error", "detail": str(exc), "ts": _now()})

    return result


async def _fill_common_fields(
    page,
    profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    log: List[Dict[str, Any]],
) -> int:
    """Fill recognizable form fields by inspecting actual element metadata."""
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
