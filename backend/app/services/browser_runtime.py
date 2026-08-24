"""Android-aware browser runtime facade.

The previously certified implementation is retained byte-for-byte in
``browser_runtime_base``. This facade changes only the external Android CDP
attachment contract: native Chromium may need materially longer than ten
seconds after the websocket is connected for Playwright to finish its CDP
handshake. The old retry loop restarted that handshake every ten seconds and
could therefore never succeed on a slow physical device.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from app.config import get_settings
from app.services import browser_runtime_base as _base
from app.services.browser_runtime_base import (
    BrowserRuntimeError,
    ExternalBrowserProcess,
    RetainableBrowserRuntime,
    _normalize_external_cdp_endpoint,
    _select_context_page,
    _wait_for_external_cdp_endpoint,
    current_browser_node_id,
    handoff_storage_root,
)

# Re-export the established runtime surface, including internal helpers used by
# focused tests. The facade's own dependencies are imported explicitly so static
# analysis and IDE navigation do not have to infer names injected by this loop.
# Explicit definitions below replace only the Android external CDP path.
for _name in dir(_base):
    if _name.startswith("__") or _name in globals():
        continue
    globals()[_name] = getattr(_base, _name)

EXTERNAL_CDP_CONNECT_TIMEOUT_SECONDS = 60
EXTERNAL_CDP_ATTACH_ATTEMPT_TIMEOUT_SECONDS = 45


async def _connect_external_playwright_over_cdp(playwright: Any, endpoint: str) -> Any:
    """Attach Playwright to native Android Chromium with a real handshake budget.

    A reachable ``/json/version`` endpoint proves only that DevTools HTTP is
    alive. It does not prove Playwright has completed its websocket/session
    handshake. Give one attach attempt up to 45 seconds and retain a 60-second
    total bound for a second attempt if the first genuinely fails.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + EXTERNAL_CDP_CONNECT_TIMEOUT_SECONDS
    attach_error = ""

    while loop.time() < deadline:
        try:
            remaining_ms = max(1_000, int((deadline - loop.time()) * 1000))
            attempt_timeout_ms = min(
                EXTERNAL_CDP_ATTACH_ATTEMPT_TIMEOUT_SECONDS * 1000,
                remaining_ms,
            )
            return await playwright.chromium.connect_over_cdp(
                endpoint,
                timeout=attempt_timeout_ms,
            )
        except Exception as exc:
            attach_error = str(exc)
            if loop.time() >= deadline:
                break
            await asyncio.sleep(1)

    raise BrowserRuntimeError(
        "Playwright could not attach to the configured Android/native Chromium "
        f"endpoint {endpoint} within {EXTERNAL_CDP_CONNECT_TIMEOUT_SECONDS} seconds: "
        f"{attach_error[:300]}"
    )


async def attach_retainable_browser(
    playwright: Any,
    *,
    cdp_endpoint: str,
    viewport: Optional[Dict[str, int]] = None,
) -> RetainableBrowserRuntime:
    """Attach to Android/native Chromium without launching or terminating it."""

    endpoint = _normalize_external_cdp_endpoint(cdp_endpoint)
    await _wait_for_external_cdp_endpoint(endpoint)
    browser = await _connect_external_playwright_over_cdp(playwright, endpoint)
    context, page = await _select_context_page(
        browser,
        viewport=viewport,
        resize_viewport=False,
    )

    session_id = str(uuid4())
    session_dir = handoff_storage_root() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    return RetainableBrowserRuntime(
        process=ExternalBrowserProcess(endpoint),
        cdp_endpoint=endpoint,
        browser_session_id=session_id,
        browser_profile_path="",
        browser_node_id=current_browser_node_id(),
        browser_provider="local_cdp",
        owns_process=False,
        browser=browser,
        context=context,
        page=page,
        session_dir=session_dir,
    )


async def probe_external_playwright_cdp(endpoint: str) -> Dict[str, Any]:
    """Prove the same Playwright-over-CDP path used by application workers.

    The browser is externally owned by Termux. The probe disconnects its
    Playwright controller when the context manager exits and never terminates
    native Chromium.
    """

    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        runtime = await attach_retainable_browser(
            playwright,
            cdp_endpoint=endpoint,
        )
        try:
            contexts = list(runtime.browser.contexts)
            if not contexts:
                raise BrowserRuntimeError(
                    "Android/native Chromium accepted Playwright CDP but exposed no browser context."
                )
            pages = list(contexts[0].pages)
            return {
                "playwright_attach_ready": True,
                "cdp_endpoint": runtime.cdp_endpoint,
                "context_count": len(contexts),
                "page_count": len(pages),
                "current_url": str(runtime.page.url or ""),
                "browser_owned_by_jobtomatik": bool(runtime.owns_process),
            }
        finally:
            # ExternalBrowserProcess.terminate is intentionally a no-op.
            runtime.terminate(remove_profile=False)


async def probe_external_playwright_cdp_attachment(endpoint: str) -> Dict[str, Any]:
    """Prove only that Playwright can complete the external CDP handshake.

    Launcher recovery must distinguish an unusable DevTools connection from a
    healthy retained browser whose pages are intentionally ambiguous. Page
    selection remains part of the worker/runtime acceptance probe, but it must
    not authorize terminating the externally owned Chromium process.
    """

    from playwright.async_api import async_playwright

    normalized_endpoint = _normalize_external_cdp_endpoint(endpoint)
    await _wait_for_external_cdp_endpoint(normalized_endpoint)
    async with async_playwright() as playwright:
        browser = await _connect_external_playwright_over_cdp(
            playwright,
            normalized_endpoint,
        )
        return {
            "playwright_attach_ready": True,
            "cdp_endpoint": normalized_endpoint,
            "context_count": len(list(browser.contexts)),
            "browser_owned_by_jobtomatik": False,
        }


async def launch_application_browser(
    playwright: Any,
    *,
    viewport: Optional[Dict[str, int]] = None,
) -> RetainableBrowserRuntime:
    """Use external Android Chromium when configured, otherwise launch locally."""

    settings = get_settings()
    cdp_endpoint = (settings.application_browser_cdp_endpoint or "").strip()
    if cdp_endpoint:
        return await attach_retainable_browser(
            playwright,
            cdp_endpoint=cdp_endpoint,
            viewport=viewport,
        )
    return await _base.launch_retainable_browser(
        playwright,
        viewport=viewport,
        profile_dir=Path(settings.application_browser_profile_dir).expanduser(),
        headless=bool(settings.application_browser_headless),
        executable_path=(settings.application_browser_executable or "").strip(),
    )
