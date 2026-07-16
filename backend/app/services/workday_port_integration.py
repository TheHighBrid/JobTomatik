"""Runtime integration for the Workday doorway ported from JobSniffing.

The donor adapter deliberately owns strict target recognition and the bounded Apply
transition. This module connects that doorway to JobTomatik's async runtime without
changing its safety model:

* public CXS metadata uses the complete external job path rather than requisition ID
* a Workday Apply popup or new tab becomes the active ATS surface
* a no-op SPA Apply click may fall back once to the public same-origin ``/apply`` route
* Workday's application-adventure screen advances only through ``applyManually``
* nonessential cookies are declined when their notice blocks the application controls
* retained evidence continues to exclude query strings and fragments

No credentials are entered, no account is created, no prior application is reused, and
no challenge is bypassed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote, urljoin, urlparse

import httpx

from app.services import ats_workday


_ORIGINAL_FETCH = ats_workday.fetch_workday_job_metadata
_ORIGINAL_INSPECT = ats_workday.inspect_workday_job_metadata
_ORIGINAL_PREPARE = ats_workday.WorkdayAdapter.prepare
_ORIGINAL_RESOLVE = ats_workday.WorkdayAdapter.resolve_surface


def _candidate_job_path(target: ats_workday.WorkdayTarget) -> str:
    """Return the full Candidate Experience path beginning with ``job/``."""

    segments = [segment for segment in urlparse(target.safe_url).path.split("/") if segment]
    if segments and ats_workday._LOCALE_RE.fullmatch(segments[0]):
        segments = segments[1:]
    lowered = [segment.casefold() for segment in segments]
    try:
        job_index = lowered.index("job")
    except ValueError:
        return ""
    return "/".join(segments[job_index:])


def _safe_path_url(value: str) -> str:
    parsed = urlparse(value or "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def workday_cxs_full_job_url(target: ats_workday.WorkdayTarget) -> str:
    path = _candidate_job_path(target)
    if not path:
        return ats_workday.workday_cxs_job_url(target)
    encoded_path = quote(path, safe="/._-")
    return (
        f"https://{target.host}/wday/cxs/{quote(target.tenant)}/"
        f"{quote(target.site)}/{encoded_path}"
    )


def workday_public_apply_url(target: ats_workday.WorkdayTarget) -> str:
    return f"{target.safe_url.rstrip('/')}/apply"


async def _fetch_full_path_metadata(
    target: ats_workday.WorkdayTarget,
    *,
    timeout: float = 25.0,
) -> Dict[str, Any]:
    url = workday_cxs_full_job_url(target)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Workday CXS job metadata did not return an object.")
    return payload


def _inspect_with_actual_cxs_url(
    payload: Dict[str, Any],
    target: ats_workday.WorkdayTarget,
) -> Dict[str, Any]:
    value = _ORIGINAL_INSPECT(payload, target)
    value["cxs_url"] = workday_cxs_full_job_url(target)
    value["cxs_uses_full_external_path"] = bool(_candidate_job_path(target))
    value["public_apply_url"] = workday_public_apply_url(target)
    return value


def _owner_page(surface: Any) -> Optional[Any]:
    if hasattr(surface, "context") and hasattr(surface, "wait_for_timeout"):
        return surface
    try:
        return surface.page
    except Exception:
        return None


async def _visible_application_boundary(page: Any) -> bool:
    """Recognize only application, login, or account controls.

    Generic dialogs are deliberately excluded because Workday job pages commonly show
    cookie, accessibility, or informational dialogs before the application begins.
    """

    for selector in (
        '[data-automation-id="bottom-navigation-next-button"]',
        '[data-automation-id*="submit" i]',
        'input[type="file"]',
        'input[type="password"]',
        '[data-automation-id*="createAccount" i]',
    ):
        try:
            control = await page.query_selector(selector)
            if control and await control.is_visible():
                return True
        except Exception:
            continue
    return False


async def _decline_nonessential_cookies(page: Any, log: list[Dict[str, Any]]) -> bool:
    selector = '[data-automation-id="legalNoticeDeclineButton"]'
    try:
        control = await page.query_selector(selector)
        if not control or not await control.is_visible():
            return False
        await control.click(timeout=5000)
        await page.wait_for_timeout(350)
        log.append({
            "action": "workday_nonessential_cookies_declined",
            "selector": selector,
            "essential_cookies_unchanged": True,
            "application_answer_changed": False,
        })
        return True
    except Exception as exc:
        log.append({
            "action": "workday_cookie_notice_decline_failed",
            "selector": selector,
            "detail": f"{type(exc).__name__}: {str(exc)[:240]}",
            "application_answer_changed": False,
        })
        return False


async def _advance_apply_adventure(page: Any, log: list[Dict[str, Any]]) -> bool:
    """Choose only Workday's explicit same-origin manual-application path."""

    await _decline_nonessential_cookies(page, log)
    selector = '[data-automation-id="applyManually"]'
    try:
        control = await page.query_selector(selector)
        if not control or not await control.is_visible():
            return False
        href = str(await control.get_attribute("href") or "")
        target_url = urljoin(str(getattr(page, "url", "") or ""), href)
        current_url = str(getattr(page, "url", "") or "")
        same_origin = urlparse(target_url).netloc == urlparse(current_url).netloc
        if not same_origin:
            log.append({
                "action": "workday_apply_manual_external_target_blocked",
                "selector": selector,
                "target_url": _safe_path_url(target_url),
                "bypass_attempted": False,
            })
            return False

        before_url = current_url
        try:
            await control.click(timeout=8000)
        except Exception:
            if not target_url:
                raise
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        await page.wait_for_timeout(500)

        after_url = str(getattr(page, "url", "") or "")
        if after_url == before_url and target_url:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            after_url = str(getattr(page, "url", "") or "")

        log.append({
            "action": "workday_apply_manually_selected",
            "selector": selector,
            "source_url": _safe_path_url(before_url),
            "active_url": _safe_path_url(after_url),
            "same_origin": True,
            "bounded_apply_transition": True,
            "autofill_with_resume_selected": False,
            "last_application_reused": False,
            "credentials_entered": False,
            "account_created": False,
            "bypass_attempted": False,
        })
        return True
    except Exception as exc:
        log.append({
            "action": "workday_apply_manually_transition_failed",
            "selector": selector,
            "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
            "credentials_entered": False,
            "account_created": False,
            "bypass_attempted": False,
        })
        return False


async def _prepare_with_popup_capture(
    self: ats_workday.WorkdayAdapter,
    surface: Any,
    log: list[Dict[str, Any]],
) -> None:
    page = _owner_page(surface)
    context = getattr(page, "context", None) if page is not None else None
    before_pages = list(context.pages) if context is not None else []
    before_url = str(getattr(page, "url", "") or "") if page is not None else ""
    before_log_count = len(log)

    await _ORIGINAL_PREPARE(self, surface, log)

    if page is None:
        return
    try:
        await page.wait_for_timeout(700)
    except Exception:
        pass

    if context is not None:
        new_pages = [candidate for candidate in context.pages if candidate not in before_pages]
        if new_pages:
            active = new_pages[-1]
            try:
                await active.wait_for_load_state("domcontentloaded", timeout=12000)
            except Exception:
                pass
            await _advance_apply_adventure(active, log)
            self._jobtomatik_workday_active_page = active
            log.append({
                "action": "workday_application_popup_captured",
                "source_url": _safe_path_url(before_url),
                "active_url": _safe_path_url(str(getattr(active, "url", "") or "")),
                "popup_count": len(new_pages),
                "bounded_apply_transition": True,
                "credentials_entered": False,
                "account_created": False,
                "bypass_attempted": False,
            })
            return

    after_url = str(getattr(page, "url", "") or "")
    if after_url and after_url != before_url:
        await _advance_apply_adventure(page, log)
        log.append({
            "action": "workday_application_navigation_captured",
            "source_url": _safe_path_url(before_url),
            "active_url": _safe_path_url(str(getattr(page, "url", "") or "")),
            "bounded_apply_transition": True,
        })
        self._jobtomatik_workday_active_page = page
        return

    apply_clicked = any(
        item.get("action") == "workday_application_revealed"
        for item in log[before_log_count:]
    )
    target = ats_workday.parse_workday_target(before_url)
    if not apply_clicked or target is None or await _visible_application_boundary(page):
        return

    apply_url = workday_public_apply_url(target)
    try:
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=12000)
        except Exception:
            pass
        await _advance_apply_adventure(page, log)
        self._jobtomatik_workday_active_page = page
        log.append({
            "action": "workday_public_apply_route_fallback",
            "source_url": _safe_path_url(before_url),
            "active_url": _safe_path_url(str(getattr(page, "url", "") or "")),
            "requested_url": _safe_path_url(apply_url),
            "same_origin": urlparse(apply_url).netloc == urlparse(before_url).netloc,
            "bounded_apply_transition": True,
            "credentials_entered": False,
            "account_created": False,
            "bypass_attempted": False,
        })
    except Exception as exc:
        log.append({
            "action": "workday_public_apply_route_fallback_failed",
            "source_url": _safe_path_url(before_url),
            "requested_url": _safe_path_url(apply_url),
            "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
            "credentials_entered": False,
            "account_created": False,
            "bypass_attempted": False,
        })


async def _resolve_with_active_page(
    self: ats_workday.WorkdayAdapter,
    page: Any,
) -> Any:
    active = getattr(self, "_jobtomatik_workday_active_page", None)
    if active is not None:
        try:
            if not active.is_closed():
                return active
        except Exception:
            return active
    return await _ORIGINAL_RESOLVE(self, page)


def install_workday_port_integration() -> None:
    if getattr(ats_workday.fetch_workday_job_metadata, "_jobtomatik_full_path", False):
        return

    _fetch_full_path_metadata._jobtomatik_full_path = True
    _inspect_with_actual_cxs_url._jobtomatik_full_path = True
    _prepare_with_popup_capture._jobtomatik_popup_capture = True
    _resolve_with_active_page._jobtomatik_popup_capture = True

    ats_workday.fetch_workday_job_metadata = _fetch_full_path_metadata
    ats_workday.inspect_workday_job_metadata = _inspect_with_actual_cxs_url
    ats_workday.WorkdayAdapter.prepare = _prepare_with_popup_capture
    ats_workday.WorkdayAdapter.resolve_surface = _resolve_with_active_page


__all__ = [
    "install_workday_port_integration",
    "workday_cxs_full_job_url",
    "workday_public_apply_url",
]
