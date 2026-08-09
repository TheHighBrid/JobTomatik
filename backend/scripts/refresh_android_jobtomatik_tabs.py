#!/usr/bin/env python3
"""Refresh open JobTomatik frontend tabs after a managed Android runtime update.

A Vite page can remain open across a git pull and keep an older JavaScript module graph
and stale task state in memory. The managed Android updater uses native Chromium over
CDP, so it can safely refresh only JobTomatik localhost tabs without touching LinkedIn,
employer ATS pages, the authenticated browser profile, or an operator-selected backend
API URL.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from playwright.async_api import async_playwright

from app.services.browser_runtime import launch_application_browser


MANAGED_API_URL = "http://127.0.0.1:8010"
STALE_SUBMIT_TASK_PREFIX = "jobtomatik_submit_task_"


def is_jobtomatik_frontend_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or ""))
    except Exception:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}
        and parsed.port == 3000
    )


async def normalize_frontend_page(page) -> None:
    await page.evaluate(
        """({ stalePrefix }) => {
          // Preserve jobtomatik_api_url. The managed 8010 endpoint is only the
          // fallback default; an API URL explicitly saved by the operator must
          // survive runtime updates and tab refreshes.
          try {
            for (let i = sessionStorage.length - 1; i >= 0; i -= 1) {
              const key = sessionStorage.key(i);
              if (key && key.startsWith(stalePrefix)) sessionStorage.removeItem(key);
            }
          } catch (_) {}
        }""",
        {"stalePrefix": STALE_SUBMIT_TASK_PREFIX},
    )
    await page.reload(wait_until="domcontentloaded", timeout=20_000)


async def main() -> int:
    refreshed = 0
    async with async_playwright() as playwright:
        runtime = await launch_application_browser(playwright)
        try:
            for context in list(runtime.browser.contexts):
                for page in list(context.pages):
                    if not is_jobtomatik_frontend_url(page.url):
                        continue
                    try:
                        await normalize_frontend_page(page)
                        refreshed += 1
                    except Exception as exc:
                        print(f"ANDROID_FRONTEND_TAB_REFRESH_FAILED url={page.url} error={str(exc)[:160]}")
                        return 1
        finally:
            runtime.terminate(remove_profile=False)

    print(f"ANDROID_FRONTEND_TABS_REFRESHED={refreshed}")
    print(f"ANDROID_FRONTEND_API_DEFAULT={MANAGED_API_URL}")
    print("ANDROID_FRONTEND_SAVED_API_PRESERVED=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
