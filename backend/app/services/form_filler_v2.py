"""Policy-gated Playwright application form filler."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.answer_policy import (
    classify_question,
    resolve_runtime_policy,
    review_reason_for_question,
)
from app.services.browser_navigation import (
    detect_blocking_challenge,
    find_submit_button,
    is_allowed_url,
    is_fake_url,
    navigate_job_board_listing,
    now_iso,
)
from app.services.control_engine import (
    CONTROL_ENGINE_VERSION,
    element_descriptor,
    fill_policy_controls,
    normalize_text,
)

_SEARCH_FIELDS = {
    "q", "l", "what", "where", "keywords", "location",
    "searchstring", "locationstring", "recherchestring", "localisationstring",
}
SAFE_PROFILE_FIELDS: List[Tuple[str, str]] = [
    (r"\bfirst\s*[_\-]?name\b|\bfname\b|given[\s_]name|prenom", "first_name"),
    (r"\blast\s*[_\-]?name\b|\blname\b|surname|family[\s_]name|nom\b", "last_name"),
    (r"\bfull[\s_]name\b|\byour[\s_]name\b|candidate[\s_]name|complete[\s_]name", "full_name"),
    (r"\bemail\b|e[_\-]?mail|courriel", "email"),
    (r"\bphone\b|\bmobile\b|\btelephone\b|\btel\b|\bcell\b|\bphone[\s_]number", "phone"),
    (r"\bcity\b|\bville\b|\bmunicipality\b", "city"),
    (r"\bstate\b|\bprovince\b|\bregion\b|\bprov\b", "state"),
    (r"\bzip\b|\bpostal\b|\bpostcode\b|\bcode\s+postal", "postal_code"),
    (r"\baddress\b|\bstreet\b|\brue\b", "address"),
    (r"\blinkedin\b", "linkedin_url"),
    (r"\bgithub\b", "github_url"),
    (r"\bportfolio\b|\bwebsite\b|\bpersonal[\s_](?:url|site|web)\b", "portfolio_url"),
    (r"cover\s*letter|lettre\s+de\s+motivation|message\s+to\s+(?:us|employer)", "cover_letter"),
    (r"\bcurrent[\s_](?:role|title|position|employer)\b|\bjob[\s_]title\b", "current_role"),
    (r"\byears[\s_](?:of[\s_])?experience\b|\bexperience[\s_]years\b", "years_experience"),
]


def _first_name(profile: Dict[str, Any]) -> str:
    parts = (profile.get("full_name") or "").split()
    return parts[0] if parts else ""


def _last_name(profile: Dict[str, Any]) -> str:
    parts = (profile.get("full_name") or "").split()
    return " ".join(parts[1:]) if len(parts) > 1 else ""


def _address_parts(address: str):
    pieces = [piece.strip() for piece in address.split(",")]
    city = pieces[0] if pieces else ""
    province = pieces[1].split()[0] if len(pieces) > 1 and pieces[1] else ""
    postal_match = re.search(
        r"\b(?:[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z][ -]?\d[ABCEGHJ-NPRSTV-Z]\d|"
        r"\d{5}(?:-\d{4})?)\b",
        address,
        flags=re.IGNORECASE,
    )
    return city, province, postal_match.group().upper() if postal_match else ""


def _profile_values(profile: Dict[str, Any], cover_letter: str) -> Dict[str, str]:
    address = profile.get("address") or ""
    city, province, postal_code = _address_parts(address)
    profile_data = profile.get("profile_data") or {}
    return {
        "first_name": profile.get("first_name") or _first_name(profile),
        "last_name": profile.get("last_name") or _last_name(profile),
        "full_name": profile.get("full_name") or "",
        "email": profile.get("email") or "",
        "phone": profile.get("phone") or "",
        "city": profile.get("city") or city,
        "state": profile.get("state") or profile.get("province") or province,
        "postal_code": profile.get("postal_code") or postal_code,
        "address": address,
        "linkedin_url": profile.get("linkedin_url") or "",
        "github_url": profile.get("github_url") or "",
        "portfolio_url": profile.get("portfolio_url") or "",
        "cover_letter": cover_letter or "",
        "current_role": profile_data.get("current_role") or profile.get("current_role") or "",
        "years_experience": str(
            profile_data.get("years_experience") or profile.get("years_experience") or ""
        ),
    }


def _safe_field(descriptor: str) -> Optional[str]:
    for pattern, key in SAFE_PROFILE_FIELDS:
        if re.search(pattern, descriptor, flags=re.IGNORECASE):
            return key
    return None


async def _required(element) -> bool:
    return (
        await element.get_attribute("required") is not None
        or normalize_text(await element.get_attribute("aria-required")) == "true"
        or normalize_text(await element.get_attribute("data-required")) == "true"
    )


def _append_review(
    items: List[Dict[str, Any]], *, descriptor: str,
    policy: Dict[str, Any], control_type: str,
    reason_code: Optional[str] = None, summary: Optional[str] = None,
) -> None:
    reason = reason_code or review_reason_for_question(policy)
    signature = (reason, descriptor, control_type)
    for existing in items:
        if signature == (
            existing.get("reason_code"),
            existing.get("details", {}).get("descriptor"),
            existing.get("details", {}).get("control_type"),
        ):
            return
    items.append({
        "reason_code": reason,
        "summary": summary or f"Approved answer required for: {descriptor}",
        "details": {
            "canonical_key": policy.get("canonical_key", "custom.unclassified"),
            "category": policy.get("category"),
            "sensitivity": policy.get("sensitivity"),
            "descriptor": descriptor,
            "control_type": control_type,
            "required": True,
            "policy_reason": policy.get("reason"),
            "control_engine_version": CONTROL_ENGINE_VERSION,
        },
    })


async def _fill_fields(page, profile, cover_letter, resume_path, log):
    values = _profile_values(profile, cover_letter)
    policies = list(profile.get("answer_policies") or [])
    review_items: List[Dict[str, Any]] = []
    filled = 0

    selector = (
        'input:not([type="hidden"]):not([type="submit"]):not([type="button"])'
        ':not([type="reset"]):not([type="checkbox"]):not([type="radio"])'
        ':not([type="file"]):not([list]),textarea'
    )
    for element in await page.query_selector_all(selector):
        try:
            if not await element.is_visible() or not await element.is_enabled():
                continue
            if await element.get_attribute("readonly") is not None:
                continue
            descriptor = await element_descriptor(page, element)
            if normalize_text(await element.get_attribute("name")) in _SEARCH_FIELDS:
                continue

            field = _safe_field(descriptor)
            if field:
                value = values.get(field, "")
                if value:
                    await element.fill(str(value))
                    if str(await element.input_value()) == str(value):
                        filled += 1
                        log.append({
                            "action": "fill", "field": field,
                            "descriptor": descriptor[:160], "source": "profile",
                            "verified": True, "ts": now_iso(),
                        })
                    else:
                        _append_review(
                            review_items, descriptor=descriptor,
                            policy=classify_question(descriptor), control_type="text",
                            reason_code="unsupported_control",
                            summary=f"Profile field could not be verified: {descriptor}",
                        )
                elif await _required(element):
                    _append_review(
                        review_items, descriptor=descriptor,
                        policy=classify_question(descriptor), control_type="text",
                        reason_code="ambiguous_question",
                        summary=f"Required profile value is missing: {descriptor or field}",
                    )
                continue

            policy = resolve_runtime_policy(descriptor, policies)
            if policy.get("can_autofill"):
                answer = str(policy.get("answer") or "")
                await element.fill(answer)
                if await element.input_value() == answer:
                    filled += 1
                    log.append({
                        "action": "fill", "descriptor": descriptor[:160],
                        "canonical_key": policy.get("canonical_key"),
                        "source": "answer_policy", "verified": True, "ts": now_iso(),
                    })
                else:
                    _append_review(
                        review_items, descriptor=descriptor, policy=policy,
                        control_type="text", reason_code="unsupported_control",
                        summary=f"Policy answer could not be verified: {descriptor}",
                    )
            elif await _required(element):
                _append_review(
                    review_items, descriptor=descriptor,
                    policy=policy, control_type="text",
                )
        except Exception as exc:
            log.append({"action": "fill_skipped", "detail": str(exc)[:200], "ts": now_iso()})

    control_outcome = await fill_policy_controls(page, policies, log)
    filled += control_outcome.filled_count
    for item in control_outcome.review_items:
        signature = (
            item.get("reason_code"),
            item.get("details", {}).get("descriptor"),
            item.get("details", {}).get("control_type"),
        )
        if not any(signature == (
            existing.get("reason_code"),
            existing.get("details", {}).get("descriptor"),
            existing.get("details", {}).get("control_type"),
        ) for existing in review_items):
            review_items.append(item)

    if resume_path and os.path.exists(resume_path):
        for file_input in await page.query_selector_all('input[type="file"]'):
            try:
                await file_input.set_input_files(resume_path)
                if await file_input.evaluate("(el) => el.files?.length || 0"):
                    filled += 1
                    log.append({"action": "upload_resume", "verified": True, "ts": now_iso()})
                    break
            except Exception as exc:
                log.append({
                    "action": "upload_resume_skipped",
                    "detail": str(exc)[:200],
                    "ts": now_iso(),
                })
    elif resume_path:
        log.append({
            "action": "upload_resume_skipped",
            "detail": "resume path not found",
            "ts": now_iso(),
        })

    return {
        "filled_count": filled,
        "review_items": review_items,
        "control_evidence": control_outcome.evidence,
        "control_passes": control_outcome.passes,
    }


async def fill_and_submit_application(
    job_url: str,
    user_profile: Dict[str, Any],
    cover_letter: str,
    resume_path: str,
    dry_run: bool = True,
) -> Dict[str, Any]:
    log: List[Dict[str, Any]] = []
    result = {
        "success": False,
        "dry_run": dry_run,
        "url": job_url,
        "log": log,
        "submitted_at": None,
        "error": None,
        "fields_filled": 0,
        "requires_manual_review": False,
        "review_items": [],
        "control_engine_version": CONTROL_ENGINE_VERSION,
        "control_evidence": [],
    }
    if not is_allowed_url(job_url):
        result["error"] = "Invalid or unsupported job URL"
        result["requires_manual_review"] = True
        return result
    if is_fake_url(job_url):
        result["error"] = "Placeholder URL; manual application required"
        result["requires_manual_review"] = True
        return result

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
            log.append({"action": "navigate", "url": job_url, "ts": now_iso()})
            try:
                await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except PlaywrightTimeoutError:
                    log.append({"action": "network_idle_timeout", "ts": now_iso()})
            except PlaywrightTimeoutError:
                log.append({"action": "navigation_timeout", "ts": now_iso()})

            await asyncio.sleep(1)
            handoff = await navigate_job_board_listing(page, log)
            result.update({
                key: handoff[key]
                for key in ("application_url", "contact_email")
                if handoff.get(key)
            })
            if handoff.get("manual_review_only"):
                result["requires_manual_review"] = True
                result["success"] = bool(dry_run)
                result["error"] = handoff.get("reason")
                await browser.close()
                return result

            challenge = await detect_blocking_challenge(page)
            if challenge:
                result["requires_manual_review"] = True
                result["success"] = bool(dry_run)
                result["error"] = challenge["summary"]
                result["review_items"] = [challenge]
                log.append({
                    "action": challenge["reason_code"],
                    "detail": challenge["summary"],
                    "ts": now_iso(),
                })
                await browser.close()
                return result

            outcome = await _fill_fields(
                page, user_profile, cover_letter, resume_path, log
            )
            result["fields_filled"] = outcome["filled_count"]
            result["review_items"] = outcome["review_items"]
            result["control_evidence"] = outcome["control_evidence"]
            result["control_passes"] = outcome["control_passes"]

            if outcome["review_items"]:
                result["requires_manual_review"] = True
                result["error"] = (
                    "Required application controls need approved, "
                    "unambiguous answer policies."
                )
                result["success"] = bool(dry_run)
            elif dry_run:
                result["success"] = True
                log.append({
                    "action": "dry_run_complete",
                    "fields_filled": result["fields_filled"],
                    "ts": now_iso(),
                })
            elif result["fields_filled"] >= 1:
                submit = await find_submit_button(page)
                if submit:
                    log.append({"action": "submit_click", "ts": now_iso()})
                    await submit.click()
                    await asyncio.sleep(3)
                    result["submitted_at"] = now_iso()
                    result["success"] = True
                    log.append({
                        "action": "submit_clicked",
                        "status": "unconfirmed",
                        "ts": now_iso(),
                    })
                else:
                    result["error"] = (
                        "Form filled but no submit button found; manual submit required."
                    )
                    result["requires_manual_review"] = True
            else:
                result["error"] = "No application form fields found; manual apply required."
                result["requires_manual_review"] = True

            await browser.close()
    except ImportError:
        result["error"] = "Playwright not installed"
        result["requires_manual_review"] = True
    except Exception as exc:
        result["error"] = str(exc)
        result["requires_manual_review"] = True
        log.append({"action": "error", "detail": str(exc)[:300], "ts": now_iso()})
    return result


_navigate_job_board_listing = navigate_job_board_listing
