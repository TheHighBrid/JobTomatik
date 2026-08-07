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
from urllib.parse import parse_qs, unquote, urljoin, urlparse

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


@dataclass
class ApplyCandidate:
    score: int
    surface: Any
    selector: str
    index: int
    text: str
    href: str
    locator_mode: bool


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


def _unwrap_linkedin_redirect(url: str) -> str:
    """Extract LinkedIn's external destination from a tracking redirect when present."""
    candidate = str(url or "")
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return candidate
    if "redir" not in (parsed.path or "").lower() and "redirect" not in (parsed.path or "").lower():
        return candidate
    query = parse_qs(parsed.query)
    for key in ("url", "dest", "destination", "redirect"):
        value = (query.get(key) or [None])[0]
        if not value:
            continue
        decoded = unquote(str(value))
        if is_allowed_url(decoded):
            return decoded
    return candidate


def _absolute_candidate_href(href: str, page_url: str) -> str:
    if not href:
        return ""
    absolute = urljoin(page_url, href)
    return _unwrap_linkedin_redirect(absolute)


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


async def _candidate_from_element(
    surface: Any,
    selector: str,
    index: int,
    element: Any,
    *,
    locator_mode: bool,
) -> Optional[ApplyCandidate]:
    if not await _actionable(element):
        return None
    try:
        text = await action_text(element)
    except Exception:
        return None
    try:
        href = str(await element.get_attribute("href") or "")
    except Exception:
        href = ""
    score = apply_candidate_score(text, href)
    if score < 0:
        return None
    return ApplyCandidate(
        score=score,
        surface=surface,
        selector=selector,
        index=index,
        text=text,
        href=href,
        locator_mode=locator_mode,
    )


async def _scan_selector(surface: Any, selector: str) -> List[ApplyCandidate]:
    """Read live Locators when available; use ElementHandles only for test doubles."""
    candidates: List[ApplyCandidate] = []
    locator_factory = getattr(surface, "locator", None)
    if callable(locator_factory):
        try:
            locator = locator_factory(selector)
            count = min(int(await locator.count()), 100)
            for index in range(count):
                candidate = await _candidate_from_element(
                    surface,
                    selector,
                    index,
                    locator.nth(index),
                    locator_mode=True,
                )
                if candidate:
                    candidates.append(candidate)
            return candidates
        except Exception:
            # LinkedIn can replace its job card while a locator is being inspected.
            # Falling through allows one compatibility scan before the outer retry.
            pass

    try:
        elements = await surface.query_selector_all(selector)
    except Exception:
        return candidates
    for index, element in enumerate(elements[:100]):
        candidate = await _candidate_from_element(
            surface,
            selector,
            index,
            element,
            locator_mode=False,
        )
        if candidate:
            candidates.append(candidate)
    return candidates


async def _rank_apply_controls(page: Any) -> List[ApplyCandidate]:
    ranked: List[ApplyCandidate] = []
    seen: set[tuple[str, str]] = set()
    surfaces = list(_candidate_surfaces(page))
    current_url = str(getattr(page, "url", "") or "")

    selector_groups: List[Iterable[str]] = [_APPLY_SELECTORS]
    if is_job_board_url(current_url):
        selector_groups.append(_JOB_BOARD_PLAIN_APPLY_SELECTORS)

    for selectors in selector_groups:
        for surface in surfaces:
            for selector in selectors:
                for candidate in await _scan_selector(surface, selector):
                    signature = (_normalized(candidate.text), candidate.href)
                    if signature in seen:
                        continue
                    seen.add(signature)
                    ranked.append(candidate)

    # The classic LinkedIn desktop page is unusually volatile and sometimes drops
    # every rollout-specific class between navigation and inspection. A broad scan is
    # therefore allowed only on known job-board pages and still goes through the
    # strict Apply scorer above.
    if not ranked and is_job_board_url(current_url):
        for surface in surfaces:
            for selector in _BROAD_APPLY_SELECTORS:
                for candidate in await _scan_selector(surface, selector):
                    signature = (_normalized(candidate.text), candidate.href)
                    if signature in seen:
                        continue
                    seen.add(signature)
                    ranked.append(candidate)

    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


async def _live_candidate_element(candidate: ApplyCandidate) -> Any:
    """Re-resolve the candidate immediately before click to survive SPA rerenders."""
    if candidate.locator_mode:
        locator = candidate.surface.locator(candidate.selector)
        count = int(await locator.count())
        if 0 <= candidate.index < count:
            element = locator.nth(candidate.index)
            try:
                current_text = await action_text(element)
                current_href = str(await element.get_attribute("href") or "")
            except Exception:
                current_text = ""
                current_href = ""
            if apply_candidate_score(current_text, current_href) >= 0:
                return element

        # Indexes can shift when LinkedIn injects banners. Match the original text or
        # href across the fresh locator collection before giving up.
        for index in range(min(count, 100)):
            element = locator.nth(index)
            try:
                text = await action_text(element)
                href = str(await element.get_attribute("href") or "")
            except Exception:
                continue
            if candidate.href and href == candidate.href:
                return element
            if candidate.text and _normalized(text) == _normalized(candidate.text):
                return element
        return None

    try:
        elements = await candidate.surface.query_selector_all(candidate.selector)
        if 0 <= candidate.index < len(elements):
            return elements[candidate.index]
    except Exception:
        return None
    return None


async def _navigate(page: Any, target_url: str, log: List[Dict[str, Any]], action: str) -> bool:
    try:
        await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        log.append({"action": action, "url": str(getattr(page, "url", "") or target_url), "ts": now_iso()})
        return True
    except Exception as exc:
        log.append({
            "action": f"{action}_failed",
            "url": target_url,
            "detail": str(exc)[:240],
            "ts": now_iso(),
        })
        return False


async def _copy_to_primary_page(page: Any, target_url: str, log: List[Dict[str, Any]]) -> str:
    if str(getattr(page, "url", "") or "") == target_url:
        return target_url
    if await _navigate(page, target_url, log, "application_entry_external_target_copied"):
        return str(getattr(page, "url", "") or target_url)
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
    last_url = before_url
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

        if current_url and current_url != last_url:
            log.append({
                "action": "application_entry_url_changed",
                "from_url": last_url,
                "to_url": current_url,
                "still_job_board": is_job_board_url(current_url),
                "ts": now_iso(),
            })
            last_url = current_url
            # A LinkedIn SPA route change is not application-target resolution. Keep
            # observing rather than prematurely treating another listing route as a
            # successful doorway.
            if not is_job_board_url(current_url):
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
    max_clicks: int = 4,
    settle_timeout_seconds: float = 12.0,
) -> Dict[str, Any]:
    """Reach an application form without ever asking a human to click Apply.

    The routine rescans controls before each click, prefers a proven external href
    when the job board exposes one, and tolerates SPA rerenders. It may traverse an
    intermediate employer page, but plain ``Apply`` is only eligible on known job
    boards so a generic ATS final-submit control cannot be mistaken for a doorway.
    """
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

    last_external_target: Optional[Dict[str, Any]] = None
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

        candidate = ranked[0]
        before_url = str(getattr(page, "url", "") or source_url)
        absolute_href = _absolute_candidate_href(candidate.href, before_url)
        log.append({
            "action": "application_entry_apply_click_started",
            "attempt": attempt,
            "score": candidate.score,
            "text": candidate.text[:160],
            "href": candidate.href[:500],
            "resolved_href": absolute_href[:500],
            "url": before_url,
            "live_locator": candidate.locator_mode,
            "ts": now_iso(),
        })

        # External anchors are deterministic and safer to follow directly than to
        # rely on a popup that a mobile/desktop LinkedIn rollout may block or rerender.
        if absolute_href and is_allowed_url(absolute_href) and not is_job_board_url(absolute_href):
            navigated = await _navigate(
                page,
                absolute_href,
                log,
                "application_entry_external_href_navigated",
            )
            if not navigated:
                continue
        else:
            try:
                element = await _live_candidate_element(candidate)
                if element is None or not await _actionable(element):
                    log.append({
                        "action": "application_entry_candidate_rerendered",
                        "attempt": attempt,
                        "text": candidate.text[:160],
                        "ts": now_iso(),
                    })
                    await page.wait_for_timeout(250)
                    continue
                await element.click(timeout=8000)
            except Exception as exc:
                # The outer loop rescans from the live DOM. Never turn a transient
                # LinkedIn rerender into a human handoff.
                log.append({
                    "action": "application_entry_apply_click_failed",
                    "attempt": attempt,
                    "detail": str(exc)[:240],
                    "rerender_retry": True,
                    "ts": now_iso(),
                })
                await page.wait_for_timeout(300)
                continue

        observed = await _observe_entry_result(
            page,
            source_url=source_url,
            before_url=before_url,
            timeout_seconds=settle_timeout_seconds,
            log=log,
        )
        if not observed:
            continue

        log.append({
            "action": "application_entry_resolved",
            "attempt": attempt,
            "url": observed.get("application_url"),
            "resolution_method": observed.get("resolution_method"),
            "application_form_detected": observed.get("application_form_detected"),
            "ts": now_iso(),
        })
        if observed.get("application_form_detected"):
            return observed

        # We reached an external employer/ATS page but not the form yet. Continue
        # through another high-confidence doorway in the same retained browser.
        target_url = str(observed.get("application_url") or "")
        if target_url and not is_job_board_url(target_url):
            last_external_target = observed
            continue
        return observed

    final_evidence = await application_form_evidence(page)
    if final_evidence.present:
        return {
            "application_url": str(getattr(page, "url", "") or source_url),
            "resolution_method": "form_detected_after_apply_retry",
            "application_form_detected": True,
            "form_evidence": final_evidence.as_dict(),
        }
    if last_external_target:
        return last_external_target

    current_url = str(getattr(page, "url", "") or source_url)
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
