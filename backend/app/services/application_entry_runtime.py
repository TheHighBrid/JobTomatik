"""Shared-browser-safe application entry for Android Runtime V2.

The native Chromium context intentionally contains user-owned tabs. Canonical
application-navigation helpers may inspect ``page.context.pages`` to discover an
Apply popup. This module presents them with a correlated view so unrelated tabs can
never become application targets.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlparse

from app.services.application_entry import (
    application_form_evidence,
    open_application_entry as _base_open_application_entry,
)
from app.services.ats_registry import detect_ats_adapter
from app.services.browser_navigation import is_job_board_url, now_iso


_KNOWN_ATS_HOST_HINTS = (
    "lever.co",
    "greenhouse.io",
    "myworkdayjobs.com",
    "workday.com",
    "ashbyhq.com",
    "smartrecruiters.com",
)


class _CorrelatedContext:
    def __init__(
        self,
        actual: Any,
        primary_proxy: "_CorrelatedPage",
        baseline_ids: set[int],
        eligible_ids: Optional[set[int]],
    ):
        self._actual = actual
        self._primary_proxy = primary_proxy
        self._baseline_ids = baseline_ids
        self._eligible_ids = eligible_ids

    @property
    def pages(self) -> List[Any]:
        """Expose the controlled page plus only causally correlated tabs."""
        result: List[Any] = [self._primary_proxy]
        try:
            actual_pages = list(self._actual.pages)
        except Exception:
            actual_pages = []
        primary_actual = self._primary_proxy._actual
        for candidate in actual_pages:
            if candidate is primary_actual:
                continue
            candidate_id = id(candidate)
            if candidate_id in self._baseline_ids:
                continue
            if self._eligible_ids is not None and candidate_id not in self._eligible_ids:
                continue
            result.append(candidate)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._actual, name)


class _CorrelatedPage:
    def __init__(
        self,
        actual: Any,
        baseline_ids: set[int],
        eligible_ids: Optional[set[int]],
    ):
        self._actual = actual
        actual_context = getattr(actual, "context", None)
        self.context = _CorrelatedContext(
            actual_context,
            self,
            baseline_ids,
            eligible_ids,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._actual, name)


def _actual_page(page: Any) -> Any:
    return page._actual if isinstance(page, _CorrelatedPage) else page


@asynccontextmanager
async def correlated_page_scope(
    page: Any,
    *,
    log: Optional[List[Dict[str, Any]]] = None,
    action: str = "application_entry_context_correlated",
) -> AsyncIterator[Any]:
    """Expose only the controlled page plus popups emitted while the scope is active."""
    if isinstance(page, _CorrelatedPage):
        yield page
        return

    actual_page = _actual_page(page)
    try:
        baseline_ids = {
            id(candidate) for candidate in list(actual_page.context.pages)
        }
    except Exception:
        baseline_ids = {id(actual_page)}

    popup_ids: set[int] = set()
    listener_installed = False

    def remember_popup(popup: Any) -> None:
        popup_ids.add(id(popup))

    try:
        actual_page.on("popup", remember_popup)
        listener_installed = True
    except Exception:
        # Minimal test doubles may not expose Playwright events. They still get the
        # baseline filter. Real Runtime V2 pages use strict page-level popup events.
        listener_installed = False

    correlated_page = _CorrelatedPage(
        actual_page,
        baseline_ids,
        popup_ids if listener_installed else None,
    )
    if log is not None:
        log.append({
            "action": action,
            "preexisting_page_count": len(baseline_ids),
            "preexisting_tabs_eligible_as_popups": False,
            "page_popup_event_correlation": listener_installed,
        })

    try:
        yield correlated_page
    finally:
        if listener_installed:
            try:
                actual_page.remove_listener("popup", remember_popup)
            except Exception:
                pass


async def _opener_correlated_ids(page: Any) -> set[int]:
    """Return existing tabs whose Playwright opener is the controlled page."""
    actual_page = _actual_page(page)
    try:
        candidates = list(actual_page.context.pages)
    except Exception:
        candidates = []

    correlated: set[int] = set()
    for candidate in candidates:
        if candidate is actual_page:
            continue
        try:
            opener_getter = getattr(candidate, "opener", None)
            if opener_getter is None:
                continue
            opener = opener_getter()
            if hasattr(opener, "__await__"):
                opener = await opener
        except Exception:
            continue
        if _actual_page(opener) is actual_page:
            correlated.add(id(candidate))
    return correlated


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _known_ats_url(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return any(host == hint or host.endswith("." + hint) for hint in _KNOWN_ATS_HOST_HINTS)


async def _candidate_application_evidence(
    candidate: Any,
    source_url: str,
) -> Optional[Dict[str, Any]]:
    target_url = str(getattr(candidate, "url", "") or "")
    if (
        not _is_http_url(target_url)
        or target_url == source_url
        or is_job_board_url(target_url)
    ):
        return None

    form_evidence: Dict[str, Any] = {}
    form_detected = False
    try:
        evidence = await application_form_evidence(candidate)
        form_detected = bool(evidence.present)
        form_evidence = evidence.as_dict()
    except Exception:
        pass

    adapter_name = ""
    adapter_version = ""
    try:
        adapter = await detect_ats_adapter(candidate, target_url)
        adapter_name = str(getattr(adapter, "name", "") or "")
        adapter_version = str(getattr(adapter, "version", "") or "")
    except Exception:
        pass

    trusted_ats = bool(
        adapter_name and adapter_name.lower() not in {"generic", "unknown"}
    ) or _known_ats_url(target_url)
    if not form_detected and not trusted_ats:
        return None

    return {
        "status": "resolved",
        "application_url": target_url,
        "application_form_detected": form_detected,
        "form_evidence": form_evidence,
        "trusted_ats_adapter": adapter_name or None,
        "trusted_ats_adapter_version": adapter_version or None,
        "proof": "application_form" if form_detected else "supported_ats",
    }


async def _correlated_candidates(page: Any) -> List[Any]:
    """Return the controlled page plus only tabs causally owned by it."""
    if isinstance(page, _CorrelatedPage):
        try:
            return list(page.context.pages)
        except Exception:
            return [page]

    actual_page = _actual_page(page)
    opener_ids = await _opener_correlated_ids(actual_page)
    result: List[Any] = [actual_page]
    try:
        for candidate in list(actual_page.context.pages):
            if candidate is actual_page:
                continue
            if id(candidate) in opener_ids:
                result.append(candidate)
    except Exception:
        pass
    return result


async def correlated_application_target_evidence(
    page: Any,
    source_url: str,
    log: Optional[List[Dict[str, Any]]] = None,
    *,
    settle_timeout_seconds: float = 5.0,
) -> Dict[str, Any]:
    """Resolve a causally correlated target only when application evidence exists.

    Opener ownership is necessary but intentionally not sufficient: OAuth/help/privacy
    child tabs are correlated too. A recovered candidate must additionally expose an
    application form or a supported ATS identity. Loading opener-correlated pages are
    kept eligible for a bounded settle window instead of being re-baselined away.
    """
    candidates = await _correlated_candidates(page)

    # First inspect already-loaded candidates without letting a blank child delay a
    # proven application target that is already available.
    pending: List[Any] = []
    for candidate in reversed(candidates):
        candidate_url = str(getattr(candidate, "url", "") or "")
        if _is_http_url(candidate_url):
            proven = await _candidate_application_evidence(candidate, source_url)
            if proven:
                if log is not None:
                    log.append({
                        "action": "correlated_application_target_proven",
                        "url": proven["application_url"],
                        "source_url": source_url,
                        "proof": proven["proof"],
                        "ts": now_iso(),
                    })
                return proven
        elif candidate is not _actual_page(page):
            pending.append(candidate)

    timeout = max(0.0, float(settle_timeout_seconds or 0.0))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while pending and loop.time() < deadline:
        await asyncio.sleep(0.1)
        still_pending: List[Any] = []
        for candidate in pending:
            candidate_url = str(getattr(candidate, "url", "") or "")
            if not _is_http_url(candidate_url):
                still_pending.append(candidate)
                continue
            proven = await _candidate_application_evidence(candidate, source_url)
            if proven:
                if log is not None:
                    log.append({
                        "action": "correlated_application_target_proven_after_settle",
                        "url": proven["application_url"],
                        "source_url": source_url,
                        "proof": proven["proof"],
                        "ts": now_iso(),
                    })
                return proven
        pending = still_pending

    if pending:
        if log is not None:
            log.append({
                "action": "correlated_application_target_still_loading",
                "source_url": source_url,
                "pending_correlated_pages": len(pending),
                "fallback_rebaseline_allowed": False,
                "ts": now_iso(),
            })
        return {
            "status": "pending",
            "application_url": None,
            "application_form_detected": False,
            "form_evidence": {},
            "trusted_ats_adapter": None,
            "trusted_ats_adapter_version": None,
        }

    return {
        "status": "none",
        "application_url": None,
        "application_form_detected": False,
        "form_evidence": {},
        "trusted_ats_adapter": None,
        "trusted_ats_adapter_version": None,
    }


async def correlated_external_target_from_browser(
    page: Any,
    source_url: str,
    log: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Return only an evidence-qualified target owned by the controlled page."""
    result = await correlated_application_target_evidence(page, source_url, log)
    return str(result.get("application_url") or "") or None


async def open_application_entry(
    page: Any,
    log: List[Dict[str, Any]],
    *,
    max_clicks: int = 4,
    settle_timeout_seconds: float = 12.0,
) -> Dict[str, Any]:
    """Run canonical entry logic without exposing unrelated shared-browser tabs."""
    async with correlated_page_scope(page, log=log) as correlated_page:
        return await _base_open_application_entry(
            correlated_page,
            log,
            max_clicks=max_clicks,
            settle_timeout_seconds=settle_timeout_seconds,
        )


# Employer continuation is imported by the worker modules after this runtime module.
# Replace the module binding once so those imports receive the same correlated view.
from app.services import employer_application_entry as _employer_application_entry

_base_continue_from_employer_landing = (
    _employer_application_entry.continue_from_employer_landing
)


async def continue_from_employer_landing(
    page: Any,
    *,
    source_url: str,
    log: List[Dict[str, Any]],
    max_steps: int = 3,
    settle_timeout_seconds: float = 12.0,
) -> Dict[str, Any]:
    """Keep popup correlation active through generic employer Apply continuation."""
    async with correlated_page_scope(
        page,
        log=log,
        action="employer_application_entry_context_correlated",
    ) as correlated_page:
        return await _base_continue_from_employer_landing(
            correlated_page,
            source_url=source_url,
            log=log,
            max_steps=max_steps,
            settle_timeout_seconds=settle_timeout_seconds,
        )


_employer_application_entry.continue_from_employer_landing = (
    continue_from_employer_landing
)


# Compatibility module: retained-browser target handoffs historically imported the
# uncorrelated helpers directly. Patch those module globals when this runtime loads.
# The main API and worker import this runtime through the application execution path.
try:
    from app.services import application_target_handoff as _application_target_handoff
except ImportError:
    _application_target_handoff = None

if _application_target_handoff is not None:
    _application_target_handoff.open_application_entry = open_application_entry
    _application_target_handoff.external_target_from_browser = (
        correlated_external_target_from_browser
    )
    _application_target_handoff._target_evidence_from_browser = (
        correlated_application_target_evidence
    )


__all__ = [
    "continue_from_employer_landing",
    "correlated_application_target_evidence",
    "correlated_external_target_from_browser",
    "correlated_page_scope",
    "open_application_entry",
]
