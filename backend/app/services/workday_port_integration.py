"""Runtime integration for the Workday doorway ported from JobSniffing.

The donor adapter deliberately owns only strict target recognition and the bounded
Apply transition. This module connects that doorway to JobTomatik's async runtime
without changing the donor contract:

* public CXS metadata uses the complete external job path rather than requisition ID
* a Workday Apply popup or new tab becomes the active ATS surface
* retained evidence continues to exclude query strings and fragments

No credentials are entered, no account is created, and no challenge is bypassed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse

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


def workday_cxs_full_job_url(target: ats_workday.WorkdayTarget) -> str:
    path = _candidate_job_path(target)
    if not path:
        return ats_workday.workday_cxs_job_url(target)
    encoded_path = quote(path, safe="/._-")
    return (
        f"https://{target.host}/wday/cxs/{quote(target.tenant)}/"
        f"{quote(target.site)}/{encoded_path}"
    )


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
    return value


def _owner_page(surface: Any) -> Optional[Any]:
    if hasattr(surface, "context") and hasattr(surface, "wait_for_timeout"):
        return surface
    try:
        return surface.page
    except Exception:
        return None


async def _prepare_with_popup_capture(
    self: ats_workday.WorkdayAdapter,
    surface: Any,
    log: list[Dict[str, Any]],
) -> None:
    page = _owner_page(surface)
    context = getattr(page, "context", None) if page is not None else None
    before_pages = list(context.pages) if context is not None else []
    before_url = str(getattr(page, "url", "") or "") if page is not None else ""

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
            self._jobtomatik_workday_active_page = active
            log.append({
                "action": "workday_application_popup_captured",
                "source_url": before_url,
                "active_url": str(getattr(active, "url", "") or ""),
                "popup_count": len(new_pages),
                "bounded_apply_transition": True,
                "credentials_entered": False,
                "account_created": False,
                "bypass_attempted": False,
            })
            return

    after_url = str(getattr(page, "url", "") or "")
    if after_url and after_url != before_url:
        log.append({
            "action": "workday_application_navigation_captured",
            "source_url": before_url,
            "active_url": after_url,
            "bounded_apply_transition": True,
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


__all__ = ["install_workday_port_integration", "workday_cxs_full_job_url"]
