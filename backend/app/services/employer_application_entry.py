"""Continue from employer job-detail pages into the actual application form.

A discovery job board can send JobTomatik to an employer-hosted job-detail page
that still contains one more plain ``Apply`` doorway. This module handles that
specific intermediate state without broadening final-submit permissions.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from app.services.application_entry import application_form_evidence
from app.services.ats_base import action_text
from app.services.browser_navigation import (
    external_target_from_browser,
    is_allowed_url,
    is_job_board_url,
    now_iso,
)

_INTERMEDIATE_APPLY_LABELS = {
    "apply",
    "apply now",
    "apply for this job",
    "apply for this position",
    "start application",
    "start your application",
    "begin application",
    "continue to application",
}

_INTERMEDIATE_APPLY_SELECTORS = (
    'a:text-is("Apply")',
    'button:text-is("Apply")',
    '[role="button"]:text-is("Apply")',
    'a:text-is("Apply now")',
    'button:text-is("Apply now")',
    '[role="button"]:text-is("Apply now")',
    'a:text-is("Apply for this job")',
    'button:text-is("Apply for this job")',
    'a:text-is("Apply for this position")',
    'button:text-is("Apply for this position")',
    'a:text-is("Start application")',
    'button:text-is("Start application")',
    'a:text-is("Begin application")',
    'button:text-is("Begin application")',
    'a[aria-label="Apply" i]',
    'button[aria-label="Apply" i]',
    '[role="button"][aria-label="Apply" i]',
)


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


async def _safe_candidate(element: Any) -> Optional[Dict[str, str]]:
    """Return descriptor only for a non-submit, non-form Apply doorway."""
    try:
        if not await element.is_visible() or not await element.is_enabled():
            return None
        text = await action_text(element)
        label = _normalized(text)
        if label not in _INTERMEDIATE_APPLY_LABELS:
            return None
        href = str(await element.get_attribute("href") or "")
        control_type = _normalized(await element.get_attribute("type") or "")
        if control_type == "submit":
            return None
        try:
            inside_form = bool(await element.evaluate("el => Boolean(el.closest('form'))"))
        except Exception:
            inside_form = False
        if inside_form:
            return None
        if href.lower().startswith(("mailto:", "tel:", "javascript:")):
            return None
        return {"text": text, "label": label, "href": href}
    except Exception:
        return None


async def _rank_safe_candidates(page: Any) -> List[tuple[Any, Dict[str, str]]]:
    candidates: List[tuple[Any, Dict[str, str]]] = []
    seen: set[tuple[str, str]] = set()
    for selector in _INTERMEDIATE_APPLY_SELECTORS:
        try:
            locator = page.locator(selector)
            count = min(int(await locator.count()), 40)
        except Exception:
            continue
        for index in range(count):
            element = locator.nth(index)
            descriptor = await _safe_candidate(element)
            if not descriptor:
                continue
            signature = (descriptor["label"], descriptor["href"])
            if signature in seen:
                continue
            seen.add(signature)
            candidates.append((element, descriptor))
    return candidates


async def _wait_for_form_or_navigation(
    page: Any,
    *,
    source_url: str,
    before_url: str,
    log: List[Dict[str, Any]],
    timeout_seconds: float,
) -> Optional[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.5, timeout_seconds)
    while loop.time() < deadline:
        evidence = await application_form_evidence(page)
        current_url = str(getattr(page, "url", "") or before_url)
        if evidence.present:
            return {
                "application_url": current_url,
                "resolution_method": "intermediate_employer_apply",
                "application_form_detected": True,
                "form_evidence": evidence.as_dict(),
            }

        external = await external_target_from_browser(page, source_url, log)
        if external and external != current_url and is_allowed_url(external):
            try:
                await page.goto(external, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                log.append({
                    "action": "intermediate_employer_popup_followed",
                    "url": str(getattr(page, "url", "") or external),
                    "ts": now_iso(),
                })
                return {
                    "application_url": str(getattr(page, "url", "") or external),
                    "resolution_method": "intermediate_employer_popup",
                    "application_form_detected": False,
                    "form_evidence": (await application_form_evidence(page)).as_dict(),
                }
            except Exception:
                pass

        if current_url != before_url:
            return {
                "application_url": current_url,
                "resolution_method": "intermediate_employer_navigation",
                "application_form_detected": False,
                "form_evidence": evidence.as_dict(),
            }
        await page.wait_for_timeout(300)
    return None


async def continue_from_employer_landing(
    page: Any,
    *,
    source_url: str,
    log: List[Dict[str, Any]],
    max_steps: int = 3,
    settle_timeout_seconds: float = 12.0,
) -> Dict[str, Any]:
    """Traverse plain Apply doorways only after leaving the discovery job board.

    Safety rules are deliberately narrow:
    - the current page must be external to the discovery job board;
    - no application form may already be present;
    - only exact Apply/start labels are considered;
    - submit controls and controls inside forms are never clicked;
    - success requires actual application-form evidence.
    """
    attempted: set[tuple[str, str, str]] = set()

    for step in range(1, max(1, int(max_steps)) + 1):
        current_url = str(getattr(page, "url", "") or "")
        if not current_url or is_job_board_url(current_url):
            return {}

        evidence = await application_form_evidence(page)
        if evidence.present:
            return {
                "application_url": current_url,
                "resolution_method": "intermediate_form_already_present",
                "application_form_detected": True,
                "form_evidence": evidence.as_dict(),
            }

        candidates = await _rank_safe_candidates(page)
        selected = None
        for element, descriptor in candidates:
            signature = (current_url, descriptor["label"], descriptor["href"])
            if signature not in attempted:
                selected = (element, descriptor, signature)
                break
        if selected is None:
            log.append({
                "action": "intermediate_employer_apply_not_found",
                "step": step,
                "url": current_url,
                "ts": now_iso(),
            })
            return {}

        element, descriptor, signature = selected
        attempted.add(signature)
        href = urljoin(current_url, descriptor["href"]) if descriptor["href"] else ""
        log.append({
            "action": "intermediate_employer_apply_started",
            "step": step,
            "url": current_url,
            "text": descriptor["text"][:160],
            "href": href[:500],
            "ts": now_iso(),
        })

        if href and is_allowed_url(href):
            try:
                await page.goto(href, wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
            except Exception as exc:
                log.append({
                    "action": "intermediate_employer_apply_failed",
                    "step": step,
                    "detail": str(exc)[:240],
                    "ts": now_iso(),
                })
                continue
        else:
            try:
                fresh_descriptor = await _safe_candidate(element)
                if not fresh_descriptor:
                    continue
                await element.click(timeout=8000)
            except Exception as exc:
                log.append({
                    "action": "intermediate_employer_apply_failed",
                    "step": step,
                    "detail": str(exc)[:240],
                    "ts": now_iso(),
                })
                continue

        observed = await _wait_for_form_or_navigation(
            page,
            source_url=source_url,
            before_url=current_url,
            log=log,
            timeout_seconds=settle_timeout_seconds,
        )
        if not observed:
            continue
        log.append({
            "action": "intermediate_employer_apply_observed",
            "step": step,
            "url": observed.get("application_url"),
            "application_form_detected": bool(observed.get("application_form_detected")),
            "ts": now_iso(),
        })
        if observed.get("application_form_detected"):
            return observed

    final = await application_form_evidence(page)
    if final.present:
        return {
            "application_url": str(getattr(page, "url", "") or ""),
            "resolution_method": "intermediate_form_detected_after_retry",
            "application_form_detected": True,
            "form_evidence": final.as_dict(),
        }
    return {}


__all__ = ["continue_from_employer_landing"]
