from __future__ import annotations

import asyncio

from playwright.async_api import async_playwright

from app.config import get_settings
from app.services.browser_runtime import launch_application_browser


async def main() -> int:
    settings = get_settings()
    endpoint = (settings.application_browser_cdp_endpoint or "").strip()
    if not endpoint:
        raise RuntimeError(
            "APPLICATION_BROWSER_CDP_ENDPOINT is empty. Set it to "
            "http://127.0.0.1:9222 in backend/.env."
        )

    async with async_playwright() as playwright:
        runtime = await launch_application_browser(playwright)
        try:
            print("ANDROID_BROWSER_CDP_CONNECTED")
            print(f"Endpoint: {runtime.cdp_endpoint}")
            print(f"Current URL: {runtime.page.url}")
            print(f"Browser owned by JobTomatik: {runtime.owns_process}")
        finally:
            runtime.terminate(remove_profile=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
