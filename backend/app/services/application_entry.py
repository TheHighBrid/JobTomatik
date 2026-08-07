"""Automatic navigation from job detail pages into the actual application form.

This module owns the doorway only. It may click high-confidence Apply controls and
follow the resulting page or popup, but it never fills fields and never clicks a
final submission control.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

from app.services.ats_base import action_text
from app.services.browser_navigation import (
    external_target_from_browser,
    is_allowed_url,
    is_job_board_url,
    now_iso,
)

_APPLY_ACCEPT = (
    "apply now",
    "apply for this job",
    "apply to this job",
    "apply for this position",
    "start application",
    "start your application",
    "begin application",
    "continue to application",
    "continue application",
    "complete application",
    "easy apply",
    "apply",
)
_APPLY_REJECT = (
    "apply filter",
    "applied filter",
    "application status",
    "view application",
    "view applications",
    "my applications",
    "submit application",
    "submit my application",
    "finish application",
    "save application",
    "withdraw application",
)
_APPLY_SELECTORS = (
    '#jobs-apply-button-id',
    'a.jobs-apply-button',
    'button.jobs-apply-button',
    '[data-tracking-control-name*="apply-link-offsite" i]',
    'a[aria-label*="apply now" i]',
    'button[aria-label*="apply now" i]',
    'a:has-text("Apply now")',
    'button:has-text("Apply now")',
    'a:has-text("Apply for this job")',
    'button:has-text("Apply for this job")',
    'a:has-text("Apply for this position")',
    'button:has-text("Apply for this position")',
    'a:has-text("Start application")',
    'button:has-text("Start application")',
    'a:has-text("Begin application")',
    'button:has-text("Begin application")',
    'a:has-text("Continue to application")',
    'button:has-text("Continue to application")',
    '[data-testid*="start-application" i]',
    '[data-cy*="start-application" i]',
)
_JOB_BOARD_PLAIN_APPLY_SELECTORS = (
    '[data-tracking-control-name*="apply" i]',
    'a[aria-label*="apply" i]',
    'button[aria-label*="apply" i]',
    '[role="button"][aria-label*="apply" i]',
    'a:text-is("Apply")',
    'button:text-is("Apply")',
    '[role="button"]:text-is("Apply")',
    'a:text-is("Easy Apply")',
    'button:text-is("Easy Apply")',
    '[role="button"]:text-is("Easy Apply")',
    '[data-testid*="apply" i]',
    '[data-cy*="apply" i]',
)
_BROAD_APPLY_SELECTORS = (
    "a",
    "button",
    '[role="button"]',
)


@dataclass
class ApplicationFormEvidence:
    present: bool
    surface_url: str
    visible_controls: int
    applicant_controls: int
    upload_controls: int
    email_controls: int
    submit_controls: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "present": self.present,
            "surface_url": self.surface_url,
            "visible_controls": self.visible_controls,
            "applicant_controls": self.applicant_controls,
            "upload_controls": self.upload_controls,
            "email_controls": self.email_controls,
            "submit_controls": self.submit_controls,
        }


def _normalized(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def apply_candidate_score(text: str, href: str = "") -> int:
    """Score only doorway actions, never final-submit or account-management actions."""
    label = _normalized(text)
    target = _normalized(href)
    if not label and not target:
        return -1
    if any(term in label for term in _APPLY_REJECT):
        return -1

    score = -1
    for index, phrase in enumerate(_APPLY_ACCEPT):
        if label == phrase:
            score = max(score, 120 - index)
        elif phrase not in {"apply", "easy apply"} and phrase in label:
            score = max(score, 90 - index)

    if score < 0 and re.search(r"\b(?:easy\s+)?apply\b", label):
        score = 55
    if any(token in target for token in ("/apply", "application", "candidate", "jobs/apply")):
        score = max(score, 65)
    if target.startswith("mailto:"):
        score = max(score, 70)
    return score


async def _surface_form_evidence(surface: Any) -> ApplicationFormEvidence:
    try:
        payload = await surface.evaluate(
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
              const controls = Array.from(document.querySelectorAll(
                'input:not([type=hidden]),textarea,select,[role=combobox],[contenteditable=true]'
              )).filter(visible);
              const textFor = (el) => [
                el.name || '', el.id || '', el.type || '', el.autocomplete || '',
                el.placeholder || '', el.getAttribute('aria-label') || '',
                el.getAttribute('data-testid') || ''
              ].join(' ').toLowerCase();
              const applicant = controls.filter((el) => /(^|[_\\-\\s])(first|last|full)[_\\-\\s]?name($|[_\\-\\s])|email|phone|mobile|resume|résumé|cv|cover[_\\-\\s]?letter|linkedin|portfolio/i.test(textFor(el)));
              const uploads = controls.filter((el) => el.tagName === 'INPUT' && el.type === 'file');
              const emails = controls.filter((el) => el.tagName === 'INPUT' && (el.type === 'email' || /email/i.test(textFor(el))));
              const submit = Array.from(document.querySelectorAll(
                'button[type=submit],input[type=submit],button,[role=button]'
              )).filter(visible).filter((el) => /submit|send application|finish|complete application/i.test(
                [el.innerText || '', el.value || '', el.getAttribute('aria-label') || ''].join(' ')
              ));
              return {
                visibleControls: controls.length,
                applicantControls: applicant.length,
                uploadControls: uploads.length,
                emailControls: emails.length,
                submitControls: submit.length,
                url: location.href,
              };
            }"""
        )
    except Exception:
        payload = {
            "visibleControls": 0,
            "applicantControls": 0,
            "uploadControls": 0,
            "emailControls": 0,
            "submitControls": 0,
            "url": str(getattr(surface, "url", "") or ""),
        }

    visible_controls = int(payload.get("visibleControls") or 0)
    applicant_controls = int(payload.get("applicantControls") or 0)
    upload_controls = int(payload.get("uploadControls") or 0)
    email_controls = int(payload.get("emailControls") or 0)
    submit_controls = int(payload.get("submitControls") or 0)
    present = bool(
        applicant_controls >= 2
        or (email_controls >= 1 and visible_controls >= 2)
        or (upload_controls >= 1 and visible_controls >= 2)
        or (applicant_controls >= 1 and submit_controls >= 1 and visible_controls >= 2)
    )
    return ApplicationFormEvidence(
        present=present,
        surface_url=str(payload.get("url") or getattr(surface, "url", "") or ""),
        visible_controls=visible_controls,
        applicant_controls=applicant_controls,
        upload_controls=upload_controls,
        email_controls=email_controls,
        submit_controls=submit_controls,
    )


def _candidate_surfaces(page: Any) -> Iterable[Any]:
    yield page
    try:
        for frame in list(page.frames):
            if frame is not page.main_frame:
                yield frame
    except Exception:
        return


async def application_form_evidence(page: Any) -> ApplicationFormEvidence:
    best = ApplicationFormEvidence(False, str(getattr(page, "url", "") or ""), 0, 0, 0, 0, 0)
    for surface in _candidate_surfaces(page):
        evidence = await _surface_form_evidence(surface)
        if evidence.present:
            return evidence
        if evidence.applicant_controls > best.applicant_controls:
            best = evidence
    return best


async def application_form_present(page: Any) -> bool:
    return (await application_form_evidence(page)).present


async def _actionable(element: Any) -> bool:
    try:
        if not await element.is_visible():
            return False
    except Exception:
        return False
    try:
        if not await element.is_enabled():
            return False
    except Exception:
        return False
    return True


async def _append_ranked_controls(
    ranked: List[tuple[int, Any, Any, str, str]],
    seen: set[int],
    surface: Any,
    selectors: Iterable[str],
) -> None:
    for selector in selectors:
        try:
            controls = await surface.query_selector_all(selector)
        except Exception:
            continue
        for control in controls:
            identity = id(control)
            if identity in seen or not await _actionable(control):
                continue
            seen.add(identity)
            text = await action_text(control)
            try:
                href = str(await control.get_attribute("href") or "")
            except Exception:
                href = ""
            score = apply_candidate_score(text, href)
            if score >= 0:
                ranked.append((score, surface, control, text, href))


async def _rank_apply_controls(page: Any) -> List[tuple[int, Any, Any, str, str]]:
    ranked: List[tuple[int, Any, Any, str, str]] = []
    seen: set[int] = set()
    surfaces = list(_candidate_surfaces(page))

    for surface in surfaces:
        await _append_ranked_controls(ranked, seen, surface, _APPLY_SELECTORS)

    current_url = str(getattr(page, "url", "") or "")
    if is_job_board_url(current_url):
        for surface in surfaces:
            await _append_ranked_controls(
                ranked,
                seen,
                surface,
                _JOB_BOARD_PLAIN_APPLY_SELECTORS,
            )

        # LinkedIn's classic desktop markup sometimes exposes a plain text anchor
        # whose classes and tracking attributes vary by rollout. Scan broad
        # interactive controls only on a known job-board listing, then rely on the
        # strict scorer to reject filters and application-management actions.
        if not ranked:
            for surface in surfaces:
                await _append_ranked_controls(
                    ranked,
                    seen,
                    surface,
                    _BROAD_APPLY_SELECTORS,
                )

    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


async def _copy_to_primary_page(page: Any, target_url: str, log: List[Dict[str, Any]]) -> str:
    if str(getattr(page, "url", "") or "") == target_url:
        return target_url
    try:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        return str(getattr(page, "url", "") or target_url)
    except Exception as exc:
        log.append({
            "action": "application_entry_copy_failed",
            "url": target_url,
            "detail": str(exc)[:200],
            "ts": now_iso(),
        })
        return target_url


async def _observe_entry_result(
    page: Any,
    *,
    source_url: str,
    before_url: str,
    timeout_seconds: float,
    log: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.5, timeout_seconds)
    while loop.time() < deadline:
        external = await external_target_from_browser(page, source_url, log)
        if external:
            target = await _copy_to_primary_page(page, external, log)
            evidence = await application_form_evidence(page)
            return {
                "application_url": target,
                "resolution_method": "apply_control_popup",
                "application_form_detected": evidence.present,
                "form_evidence": evidence.as_dict(),
            }

        evidence = await application_form_evidence(page)
        current_url = str(getattr(page, "url", "") or "")
        if evidence.present:
            return {
                "application_url": current_url or before_url,
                "resolution_method": (
                    "apply_control_same_page_form" if current_url == before_url else "apply_control_navigation"
                ),
                "application_form_detected": True,
                "form_evidence": evidence.as_dict(),
            }
        if current_url and current_url != before_url:
            return {
                "application_url": current_url,
                "resolution_method": "apply_control_navigation",
                "application_form_detected": False,
                "form_evidence": evidence.as_dict(),
            }
        await page.wait_for_timeout(350)
    return None


async def open_application_entry(
    page: Any,
    log: List[Dict[str, Any]],
    *,
    max_clicks: int = 3,
    settle_timeout_seconds: float = 12.0,
) -> Dict[str, Any]:
    """Reach the application form without requiring a human Apply click."""
    source_url = str(getattr(page, "url", "") or "")
    initial = await application_form_evidence(page)
    if initial.present:
        log.append({
            "action": "application_form_already_present",
            "url": source_url,
            "form_evidence": initial.as_dict(),
            "ts": now_iso(),
        })
        return {
            "application_url": source_url,
            "resolution_method": "form_already_present",
            "application_form_detected": True,
            "form_evidence": initial.as_dict(),
        }

    for attempt in range(1, max(1, int(max_clicks)) + 1):
        ranked = await _rank_apply_controls(page)
        if not ranked:
            log.append({
                "action": "application_entry_apply_control_not_found",
                "attempt": attempt,
                "url": str(getattr(page, "url", "") or source_url),
                "ts": now_iso(),
            })
            break

        score, _surface, control, text, href = ranked[0]
        before_url = str(getattr(page, "url", "") or source_url)
        log.append({
            "action": "application_entry_apply_click_started",
            "attempt": attempt,
            "score": score,
            "text": text[:160],
            "href": href[:500],
            "url": before_url,
            "ts": now_iso(),
        })
        try:
            await control.click(timeout=8000)
        except Exception as exc:
            absolute_href = urljoin(before_url, href) if href else ""
            if is_allowed_url(absolute_href):
                try:
                    await page.goto(absolute_href, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    log.append({
                        "action": "application_entry_apply_click_failed",
                        "attempt": attempt,
                        "detail": str(exc)[:240],
                        "ts": now_iso(),
                    })
                    continue
            else:
                log.append({
                    "action": "application_entry_apply_click_failed",
                    "attempt": attempt,
                    "detail": str(exc)[:240],
                    "ts": now_iso(),
                })
                continue

        observed = await _observe_entry_result(
            page,
            source_url=source_url,
            before_url=before_url,
            timeout_seconds=settle_timeout_seconds,
            log=log,
        )
        if observed:
            log.append({
                "action": "application_entry_resolved",
                "attempt": attempt,
                "url": observed.get("application_url"),
                "resolution_method": observed.get("resolution_method"),
                "application_form_detected": observed.get("application_form_detected"),
                "ts": now_iso(),
            })
            return observed

    current_url = str(getattr(page, "url", "") or source_url)
    final_evidence = await application_form_evidence(page)
    log.append({
        "action": "application_entry_not_resolved",
        "source_url": source_url,
        "current_url": current_url,
        "form_evidence": final_evidence.as_dict(),
        "ts": now_iso(),
    })
    return {}


__all__ = [
    "ApplicationFormEvidence",
    "application_form_evidence",
    "application_form_present",
    "apply_candidate_score",
    "open_application_entry",
]
