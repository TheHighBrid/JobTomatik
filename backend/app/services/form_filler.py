"""
Playwright-based form filler and application submitter.
Uses stealth-mode browser automation to fill job application forms.
"""
import asyncio
import json
import re
from typing import Dict, List, Any, Optional
from datetime import datetime


async def fill_and_submit_application(
    job_url: str,
    user_profile: Dict,
    cover_letter: str,
    resume_path: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Navigate to the job application form, fill it with user data,
    attach the resume, and submit. Returns a log of actions taken.

    dry_run=True means we fill the form but do NOT click submit.
    """
    log: List[Dict] = []
    result = {
        "success": False,
        "dry_run": dry_run,
        "url": job_url,
        "log": log,
        "submitted_at": None,
        "error": None,
    }

    try:
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

            # Remove navigator.webdriver fingerprint
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)

            page = await context.new_page()

            log.append({"action": "navigate", "url": job_url, "ts": _now()})
            await page.goto(job_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            # Detect and fill common field patterns
            filled = await _fill_common_fields(page, user_profile, cover_letter, resume_path, log)

            if filled and not dry_run:
                submit_btn = await _find_submit_button(page)
                if submit_btn:
                    log.append({"action": "submit", "ts": _now()})
                    await submit_btn.click()
                    await asyncio.sleep(3)
                    result["submitted_at"] = _now()
                    result["success"] = True
                    log.append({"action": "submitted", "ts": _now(), "status": "ok"})
                else:
                    log.append({"action": "submit_skipped", "reason": "no submit button found", "ts": _now()})
                    result["success"] = False
            elif dry_run:
                result["success"] = True
                log.append({"action": "dry_run_complete", "ts": _now()})

            await browser.close()

    except ImportError:
        result["error"] = "Playwright not installed"
        log.append({"action": "error", "detail": result["error"], "ts": _now()})
    except Exception as e:
        result["error"] = str(e)
        log.append({"action": "error", "detail": str(e), "ts": _now()})

    return result


async def _fill_common_fields(
    page,
    profile: Dict,
    cover_letter: str,
    resume_path: str,
    log: List,
) -> bool:
    """Fill all recognizable form fields on the page."""
    field_map = {
        # Name fields
        r"first.?name|fname": profile.get("first_name") or _first_name(profile),
        r"last.?name|lname|surname": profile.get("last_name") or _last_name(profile),
        r"full.?name|your.?name": profile.get("full_name", ""),
        # Contact
        r"email": profile.get("email", ""),
        r"phone|mobile|telephone": profile.get("phone", ""),
        # Location
        r"city": _extract_city(profile.get("address", "")),
        r"state|province": _extract_state(profile.get("address", "")),
        r"zip|postal": _extract_zip(profile.get("address", "")),
        r"address|street": profile.get("address", ""),
        # Links
        r"linkedin": profile.get("linkedin_url", ""),
        r"github": profile.get("github_url", ""),
        r"portfolio|website|personal.?url": profile.get("portfolio_url", ""),
        # Application content
        r"cover.?letter|motivation|introduction": cover_letter,
    }

    filled_any = False
    for selector_pattern, value in field_map.items():
        if not value:
            continue
        inputs = await page.query_selector_all(
            f'input[name*="{selector_pattern}"], '
            f'input[placeholder*="{selector_pattern}"], '
            f'textarea[name*="{selector_pattern}"], '
            f'textarea[placeholder*="{selector_pattern}"]'
        )
        # Also try aria-label based selectors
        for el in inputs:
            try:
                await el.fill(str(value))
                filled_any = True
                log.append({"action": "fill", "field": selector_pattern, "ts": _now()})
            except Exception:
                pass

    # Resume upload
    if resume_path:
        file_inputs = await page.query_selector_all('input[type="file"]')
        for fi in file_inputs:
            try:
                await fi.set_input_files(resume_path)
                log.append({"action": "upload_resume", "path": resume_path, "ts": _now()})
                filled_any = True
                break
            except Exception:
                pass

    return filled_any


async def _find_submit_button(page):
    selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Submit")',
        'button:has-text("Apply")',
        'button:has-text("Send Application")',
        'button:has-text("Submit Application")',
    ]
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn:
                return btn
        except Exception:
            pass
    return None


def _now() -> str:
    return datetime.utcnow().isoformat()


def _first_name(profile: Dict) -> str:
    parts = (profile.get("full_name") or "").split()
    return parts[0] if parts else ""


def _last_name(profile: Dict) -> str:
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


def _extract_zip(address: str) -> str:
    match = re.search(r"\b\d{5}(?:-\d{4})?\b", address)
    return match.group() if match else ""
