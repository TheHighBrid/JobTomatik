"""Shared-browser-safe application entry for Android Runtime V2.

The native Chromium context intentionally contains user-owned tabs. Canonical
application-navigation helpers may inspect ``page.context.pages`` to discover an
Apply popup. This module presents them with a correlated view so unrelated tabs can
never become application targets.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional

from app.services.application_entry import open_application_entry as _base_open_application_entry
from app.services.browser_navigation import (
    external_target_from_browser as _base_external_target_from_browser,
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


async def correlated_external_target_from_browser(
    page: Any,
    source_url: str,
    log: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """Resolve only the controlled page or an existing tab opened by that page.

    This is used when a retained browser is reattached after a human security
    boundary. A popup event may have occurred before the new process attached, so
    opener ownership is the durable correlation signal. Unrelated pre-existing tabs
    remain invisible.
    """
    if isinstance(page, _CorrelatedPage):
        return await _base_external_target_from_browser(page, source_url, log)

    actual_page = _actual_page(page)
    eligible_ids = await _opener_correlated_ids(actual_page)
    correlated_page = _CorrelatedPage(actual_page, set(), eligible_ids)
    if log is not None:
        log.append({
            "action": "application_target_existing_context_correlated",
            "eligible_opener_tab_count": len(eligible_ids),
            "unrelated_preexisting_tabs_eligible": False,
        })
    return await _base_external_target_from_browser(
        correlated_page,
        source_url,
        log,
    )


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


__all__ = [
    "continue_from_employer_landing",
    "correlated_external_target_from_browser",
    "correlated_page_scope",
    "open_application_entry",
]
