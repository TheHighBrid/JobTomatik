"""Shared-browser-safe application entry for Android Runtime V2.

The native Chromium context intentionally contains user-owned tabs. The canonical
application-entry implementation may inspect ``page.context.pages`` to detect a
popup opened by Apply. Present it a filtered context so pre-existing tabs can never
be mistaken for application targets. On real Playwright pages, only popup events
emitted by the controlled page are admitted as new targets.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.application_entry import open_application_entry as _base_open_application_entry


class _CorrelatedContext:
    def __init__(
        self,
        actual: Any,
        primary_proxy: "_CorrelatedPage",
        baseline_ids: set[int],
        popup_ids: Optional[set[int]],
    ):
        self._actual = actual
        self._primary_proxy = primary_proxy
        self._baseline_ids = baseline_ids
        self._popup_ids = popup_ids

    @property
    def pages(self) -> List[Any]:
        """Expose the controlled page plus only correlated post-action popups."""
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
            if self._popup_ids is not None and candidate_id not in self._popup_ids:
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
        popup_ids: Optional[set[int]],
    ):
        self._actual = actual
        actual_context = getattr(actual, "context", None)
        self.context = _CorrelatedContext(
            actual_context,
            self,
            baseline_ids,
            popup_ids,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._actual, name)


async def open_application_entry(
    page: Any,
    log: List[Dict[str, Any]],
    *,
    max_clicks: int = 4,
    settle_timeout_seconds: float = 12.0,
) -> Dict[str, Any]:
    """Run canonical entry logic without exposing unrelated shared-browser tabs."""
    try:
        baseline_ids = {id(candidate) for candidate in list(page.context.pages)}
    except Exception:
        baseline_ids = {id(page)}

    popup_ids: set[int] = set()
    listener_installed = False

    def remember_popup(popup: Any) -> None:
        popup_ids.add(id(popup))

    try:
        page.on("popup", remember_popup)
        listener_installed = True
    except Exception:
        # Minimal test doubles do not expose Playwright events. They still get the
        # baseline filter, while real Runtime V2 pages use strict page-level popup
        # correlation.
        listener_installed = False

    correlated_page = _CorrelatedPage(
        page,
        baseline_ids,
        popup_ids if listener_installed else None,
    )
    log.append({
        "action": "application_entry_context_correlated",
        "preexisting_page_count": len(baseline_ids),
        "preexisting_tabs_eligible_as_popups": False,
        "page_popup_event_correlation": listener_installed,
    })
    try:
        return await _base_open_application_entry(
            correlated_page,
            log,
            max_clicks=max_clicks,
            settle_timeout_seconds=settle_timeout_seconds,
        )
    finally:
        if listener_installed:
            try:
                page.remove_listener("popup", remember_popup)
            except Exception:
                pass


__all__ = ["open_application_entry"]
