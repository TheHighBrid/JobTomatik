"""Public operator helpers for a retained local browser session."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

from app.services.browser_handoff import (
    BrowserHandoffUnavailable,
    _connect_local_cdp,
    _disconnect,
    terminate_retained_browser,
)
from app.services.browser_runtime import handoff_storage_root


async def evaluate_retained_browser(session: Any, expression: str) -> Any:
    """Evaluate a script in the target-verified retained browser page."""
    playwright, _, _, page = await _connect_local_cdp(session)
    try:
        value = await page.evaluate(expression)
        session.current_url = page.url
        return value
    finally:
        await _disconnect(playwright)


def terminate_and_cleanup_retained_browser(session: Any) -> bool:
    """Terminate Chromium and delete only its transient handoff directory.

    The configured application browser profile is stored outside this directory and
    is deliberately preserved. Screenshot, HTML, storage state, and Chromium logs
    produced for the transient handoff are removed.
    """
    terminated = terminate_retained_browser(session)
    raw_session_id = str(getattr(session, "browser_session_id", "") or "").strip()
    if not raw_session_id:
        return terminated
    try:
        normalized_session_id = str(UUID(raw_session_id))
    except ValueError as exc:
        raise BrowserHandoffUnavailable(
            "The retained browser session ID is invalid; transient state was not deleted."
        ) from exc

    root = handoff_storage_root().resolve()
    session_dir = (root / normalized_session_id).resolve()
    if session_dir.parent != root:
        raise BrowserHandoffUnavailable(
            "The retained browser session directory escaped the configured storage root."
        )
    shutil.rmtree(session_dir, ignore_errors=False) if session_dir.exists() else None
    return terminated


__all__ = [
    "evaluate_retained_browser",
    "terminate_and_cleanup_retained_browser",
]
