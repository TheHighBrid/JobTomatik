"""Android-aware browser runtime facade.

The previously certified implementation is retained in ``browser_runtime_base``.
This facade changes only the external Android CDP attachment contract:

- native Chromium gets a longer real Playwright handshake budget;
- health/inventory probes may observe any number of tabs without guessing which
  tab an application owns;
- application execution creates a fresh controlled tab inside the single
  authenticated browser context instead of commandeering an arbitrary retained tab.
"""

from __future__ import annotations

import asyncio
import shutil
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

for _name in dir(_base):
    if _name.startswith("__") or _name in globals():
        continue
    globals()[_name] = getattr(_base, _name)

EXTERNAL_CDP_CONNECT_TIMEOUT_SECONDS = 60
EXTERNAL_CDP_ATTACH_ATTEMPT_TIMEOUT_SECONDS = 45


class ControlledExternalBrowserRuntime(RetainableBrowserRuntime):
    """An external runtime that owns its application tab, but not Chromium."""

    controlled_page_target_id: str = ""

    def terminate(self, *, remove_profile: bool = False) -> None:
        """Close the controlled CDP target without terminating the shared browser."""

        if self.controlled_page_target_id:
            try:
                _base.httpx.get(
                    f"{self.cdp_endpoint}/json/close/{self.controlled_page_target_id}",
                    timeout=2.0,
                )
            except Exception:
                # Chromium may already have closed the tab or disconnected. Cleanup
                # remains best-effort, just like terminating an exited local process.
                pass
            self.controlled_page_target_id = ""
        if remove_profile:
            shutil.rmtree(self.session_dir, ignore_errors=True)


async def _controlled_page_target_id(context: Any, page: Any) -> str:
    """Return the durable CDP identity needed for synchronous final cleanup."""

    session = None
    try:
        session = await context.new_cdp_session(page)
        target = await session.send("Target.getTargetInfo")
        return str((target.get("targetInfo") or {}).get("targetId") or "")
    except Exception:
        return ""
    finally:
        if session is not None:
            try:
                await session.detach()
            except Exception:
                pass


async def _connect_external_playwright_over_cdp(playwright: Any, endpoint: str) -> Any:
    """Attach Playwright to native Android Chromium with a real handshake budget."""

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


async def connect_external_playwright_browser(
    playwright: Any,
    *,
    cdp_endpoint: str,
) -> tuple[str, Any]:
    """Connect to externally owned Chromium without selecting or creating a tab.

    This is the correct primitive for health checks and browser inventory work.
    Multiple retained pages are normal browser state and are not an attachment
    failure by themselves.
    """

    endpoint = _normalize_external_cdp_endpoint(cdp_endpoint)
    await _wait_for_external_cdp_endpoint(endpoint)
    browser = await _connect_external_playwright_over_cdp(playwright, endpoint)
    return endpoint, browser


def external_browser_inventory(browser: Any) -> Dict[str, Any]:
    """Describe connected browser state without selecting an application tab."""

    contexts = list(browser.contexts)
    if not contexts:
        raise BrowserRuntimeError(
            "Android/native Chromium accepted Playwright CDP but exposed no browser context."
        )
    pages = [page for context in contexts for page in list(context.pages)]
    current_url = str(pages[0].url or "") if len(pages) == 1 else ""
    return {
        "context_count": len(contexts),
        "page_count": len(pages),
        "current_url": current_url,
        "multiple_pages_present": len(pages) > 1,
    }


def _single_external_context(browser: Any) -> Any:
    contexts = list(browser.contexts)
    if not contexts:
        raise BrowserRuntimeError("Retained Chromium exposed no default browser context.")
    if len(contexts) != 1:
        raise BrowserRuntimeError(
            "Retained Chromium exposed multiple browser contexts; application tab creation is fail-closed."
        )
    return contexts[0]


async def attach_retainable_browser(
    playwright: Any,
    *,
    cdp_endpoint: str,
    viewport: Optional[Dict[str, int]] = None,
    create_controlled_page: bool = False,
) -> RetainableBrowserRuntime:
    """Attach to Android/native Chromium without launching or terminating it.

    ``create_controlled_page`` is reserved for application execution. It creates
    one new tab inside the single authenticated browser context, avoiding any
    guess based on retained tab order. The default preserves the historical
    single-existing-page fail-closed contract for callers that explicitly need it.
    """

    endpoint, browser = await connect_external_playwright_browser(
        playwright,
        cdp_endpoint=cdp_endpoint,
    )

    if create_controlled_page:
        context = _single_external_context(browser)
        page = await context.new_page()
        controlled_page_target_id = await _controlled_page_target_id(context, page)
        if not controlled_page_target_id:
            try:
                await page.close()
            except Exception:
                pass
            raise BrowserRuntimeError(
                "Could not identify the newly controlled Chromium tab for safe cleanup."
            )
        if viewport:
            await page.set_viewport_size(viewport)
    else:
        controlled_page_target_id = ""
        context, page = await _select_context_page(
            browser,
            viewport=viewport,
            resize_viewport=False,
        )

    session_id = str(uuid4())
    session_dir = handoff_storage_root() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    runtime_class = (
        ControlledExternalBrowserRuntime
        if create_controlled_page
        else RetainableBrowserRuntime
    )
    runtime = runtime_class(
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
    if create_controlled_page:
        runtime.controlled_page_target_id = controlled_page_target_id
    return runtime


async def probe_external_playwright_cdp(endpoint: str) -> Dict[str, Any]:
    """Prove Playwright-over-CDP connectivity without imposing a tab-selection rule.

    Health acceptance is about the controller handshake and browser context, not
    about choosing an application tab. Multiple retained pages are therefore
    reported as inventory rather than rejected as ambiguous.
    """

    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        normalized_endpoint, browser = await connect_external_playwright_browser(
            playwright,
            cdp_endpoint=endpoint,
        )
        inventory = external_browser_inventory(browser)
        return {
            "playwright_attach_ready": True,
            "cdp_endpoint": normalized_endpoint,
            **inventory,
            "browser_owned_by_jobtomatik": False,
        }


async def launch_application_browser(
    playwright: Any,
    *,
    viewport: Optional[Dict[str, int]] = None,
) -> RetainableBrowserRuntime:
    """Use external Android Chromium when configured, otherwise launch locally.

    External Android execution always gets a newly created controlled page inside
    the authenticated context. Existing LinkedIn, JobTomatik, ATS, or user tabs
    are never selected by position or silently repurposed.
    """

    settings = get_settings()
    cdp_endpoint = (settings.application_browser_cdp_endpoint or "").strip()
    if cdp_endpoint:
        return await attach_retainable_browser(
            playwright,
            cdp_endpoint=cdp_endpoint,
            viewport=viewport,
            create_controlled_page=True,
        )
    return await _base.launch_retainable_browser(
        playwright,
        viewport=viewport,
        profile_dir=Path(settings.application_browser_profile_dir).expanduser(),
        headless=bool(settings.application_browser_headless),
        executable_path=(settings.application_browser_executable or "").strip(),
    )
