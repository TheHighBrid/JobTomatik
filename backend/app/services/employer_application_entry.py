"""Continue from employer job-detail pages into the actual application surface.

A discovery job board can send JobTomatik to an employer-hosted job-detail page
that still contains one or more plain ``Apply`` doorways. This module handles only
those generic employer pages. Once a hosted, certified ATS page is reached, control
returns to that ATS adapter so platform-specific Apply/login behavior stays intact.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

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

# Component libraries can put Apply text inside nested spans/icons, causing the
# exact Playwright selectors above to miss the outer actionable element. The broad
# fallback is still fail-closed because _safe_candidate requires an exact semantic
# label and rejects submit controls and anything inside a form.
_INTERMEDIATE_APPLY_FALLBACK_SELECTORS = (
    "a",
    "button",
    '[role="button"]',
    'input[type="button"]',
)


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _hosted_ats_candidate(url: str) -> bool:
    """Return True only for known hosted ATS domains, not employer pages with ATS links."""
    host = (urlparse(url or "").hostname or "").lower()
    if not host:
        return False
    if host.endswith(".myworkdayjobs.com"):
        return True
    if host in {"jobs.lever.co", "jobs.eu.lever.co"}:
        return True
    if host == "jobs.ashbyhq.com":
        return True
    if host in {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"}:
        return True
    if host in {"greenhouse.io", "greenhouse.com"}:
        return True
    if host.endswith(".greenhouse.io") or host.endswith(".greenhouse.com"):
        return True
    return False


async def _trusted_hosted_ats(page: Any, current_url: str) -> Optional[Dict[str, str]]:
    """Recognize a hosted ATS only when the current URL itself is on that ATS."""
    if not _hosted_ats_candidate(current_url):
        return None
    try:
        # Local import avoids coupling module initialization to the ATS registry.
        from app.services.ats_registry import detect_ats_adapter

        adapter = await detect_ats_adapter(page, current_url)
    except Exception:
        return None
    name = str(getattr(adapter, "name", "generic") or "generic")
    if name == "generic":
        return None
    return {
        "name": name,
        "version": str(getattr(adapter, "version", "1.0.0") or "1.0.0"),
    }


async def _bring_controlled_page_to_front(page: Any) -> None:
    """Best-effort focus so the visible tab is the same page automation controls."""
    try:
        await page.bring_to_front()
    except Exception:
        pass


async def _semantic_apply_label(element: Any) -> str:
    """Return one exact doorway label without concatenating duplicate text sources.

    ``action_text`` intentionally joins aria-label, title, value and inner text. A
    perfectly ordinary ``aria-label=Apply`` button whose inner text is also ``Apply``
    therefore becomes ``apply apply``. That is useful for fuzzy matching elsewhere,
    but this strict doorway must test each semantic source independently.
    """
    values: List[str] = []
    for attr in ("aria-label", "value", "title"):
        try:
            value = await element.get_attribute(attr)
        except Exception:
            value = None
        normalized = _normalized(value)
        if normalized:
            values.append(normalized)

    try:
        text = _normalized(await element.inner_text())
    except Exception:
        text = ""
    if text:
        values.append(text)

    # Material/icon components sometimes leak icon names into innerText. Remove only
    # explicitly decorative descendants from a cloned node and test that text too.
    try:
        clean_text = _normalized(await element.evaluate(
            """el => {
              const clone = el.cloneNode(true);
              clone.querySelectorAll(
                '[aria-hidden="true"],svg,.material-icons,.material-symbols-outlined,.material-symbols-rounded,.material-symbols-sharp'
              ).forEach(node => node.remove());
              return clone.textContent || '';
            }"""
        ))
    except Exception:
        clean_text = ""
    if clean_text:
        values.append(clean_text)

    return next((value for value in values if value in _INTERMEDIATE_APPLY_LABELS), "")


async def _safe_candidate(element: Any) -> Optional[Dict[str, str]]:
    """Return descriptor only for a non-submit, non-form Apply doorway."""
    try:
        if not await element.is_visible() or not await element.is_enabled():
            return None
        label = await _semantic_apply_label(element)
        if not label:
            return None
        try:
            text = await action_text(element)
        except Exception:
            text = label
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
        return {"text": text or label, "label": label, "href": href}
    except Exception:
        return None


async def _scan_safe_candidates(
    page: Any,
    selectors: tuple[str, ...],
    *,
    seen: set[tuple[str, str]],
) -> List[tuple[Any, Dict[str, str]]]:
    candidates: List[tuple[Any, Dict[str, str]]] = []
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(int(await locator.count()), 100)
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


async def _rank_safe_candidates(page: Any) -> List[tuple[Any, Dict[str, str]]]:
    seen: set[tuple[str, str]] = set()
    candidates = await _scan_safe_candidates(
        page,
        _INTERMEDIATE_APPLY_SELECTORS,
        seen=seen,
    )
    if candidates:
        return candidates
    return await _scan_safe_candidates(
        page,
        _INTERMEDIATE_APPLY_FALLBACK_SELECTORS,
        seen=seen,
    )


async def _click_safe_candidate(
    page: Any,
    element: Any,
    descriptor: Dict[str, str],
    *,
    step: int,
    log: List[Dict[str, Any]],
) -> bool:
    """Click a verified doorway, retrying actionability-only failures safely.

    Some employer React pages render a visibly enabled Apply button beneath a layout
    layer that makes Playwright's normal pointer-actionability check time out. A force
    retry is permitted only after the control has passed all doorway safety checks,
    and the live DOM is rescanned before that retry so a rerender cannot turn the
    operation into a click on a different control.
    """
    fresh = await _safe_candidate(element)
    if not fresh:
        return False
    try:
        try:
            await element.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        await element.click(timeout=5000)
        return True
    except Exception as exc:
        log.append({
            "action": "intermediate_employer_apply_click_retry",
            "step": step,
            "detail": str(exc)[:500],
            "forced": False,
            "ts": now_iso(),
        })

    # Re-resolve from the current DOM. Matching is still strict and submit/form
    # controls remain excluded. Prefer the same exact semantic label and href.
    try:
        refreshed = await _rank_safe_candidates(page)
    except Exception:
        refreshed = []
    retry = next(
        (
            candidate
            for candidate, candidate_descriptor in refreshed
            if candidate_descriptor.get("label") == descriptor.get("label")
            and candidate_descriptor.get("href", "") == descriptor.get("href", "")
        ),
        None,
    )
    if retry is None:
        return False
    retry_descriptor = await _safe_candidate(retry)
    if not retry_descriptor:
        return False
    try:
        await retry.click(timeout=4000, force=True)
        log.append({
            "action": "intermediate_employer_apply_force_clicked",
            "step": step,
            "label": retry_descriptor.get("label"),
            "submit_control": False,
            "inside_form": False,
            "ts": now_iso(),
        })
        return True
    except Exception as exc:
        log.append({
            "action": "intermediate_employer_apply_failed",
            "step": step,
            "detail": str(exc)[:500],
            "forced": True,
            "ts": now_iso(),
        })
        return False


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
            await _bring_controlled_page_to_front(page)
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
                await _bring_controlled_page_to_front(page)
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
            await _bring_controlled_page_to_front(page)
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
    """Traverse ordinary employer Apply doorways without crossing ATS safety ownership.

    Safety rules are deliberately narrow:
    - the current page must be external to the discovery job board;
    - no application form may already be present;
    - hosted certified ATS pages are returned to their adapter untouched;
    - only exact Apply/start labels are considered on generic employer pages;
    - submit controls and controls inside forms are never clicked.
    """
    attempted: set[tuple[str, str, str]] = set()

    for step in range(1, max(1, int(max_steps)) + 1):
        await _bring_controlled_page_to_front(page)
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

        hosted_ats = await _trusted_hosted_ats(page, current_url)
        if hosted_ats:
            log.append({
                "action": "intermediate_employer_trusted_ats_reached",
                "step": step,
                "url": current_url,
                "adapter": hosted_ats["name"],
                "adapter_version": hosted_ats["version"],
                "generic_apply_clicked": False,
                "ts": now_iso(),
            })
            return {
                "application_url": current_url,
                "resolution_method": "trusted_ats_entry",
                "application_form_detected": False,
                "form_evidence": evidence.as_dict(),
                "trusted_ats_adapter": hosted_ats["name"],
                "trusted_ats_adapter_version": hosted_ats["version"],
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
            "label": descriptor["label"],
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
                await _bring_controlled_page_to_front(page)
            except Exception as exc:
                log.append({
                    "action": "intermediate_employer_apply_failed",
                    "step": step,
                    "detail": str(exc)[:500],
                    "ts": now_iso(),
                })
                continue
        else:
            clicked = await _click_safe_candidate(
                page,
                element,
                descriptor,
                step=step,
                log=log,
            )
            if not clicked:
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
        await _bring_controlled_page_to_front(page)
        return {
            "application_url": str(getattr(page, "url", "") or ""),
            "resolution_method": "intermediate_form_detected_after_retry",
            "application_form_detected": True,
            "form_evidence": final.as_dict(),
        }
    return {}


__all__ = ["continue_from_employer_landing"]
