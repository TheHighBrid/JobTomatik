from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from playwright.async_api import async_playwright

from app.services.browser_runtime import launch_application_browser


LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
LINKEDIN_AUTH_COOKIE = "li_at"


async def _linkedin_login_saved(context: Any) -> bool:
    cookies = await context.cookies("https://www.linkedin.com")
    return any(
        cookie.get("name") == LINKEDIN_AUTH_COOKIE and cookie.get("value")
        for cookie in cookies
    )


async def _wait_for_saved_login(runtime: Any) -> None:
    print("\nJobTomatik's dedicated Chromium profile is open.")
    print("Log into LinkedIn and complete any MFA, verification, or consent screens.")
    print("There is no login countdown. This process waits until the LinkedIn session cookie is saved.")
    print("Press Ctrl+C only if you want to cancel.\n")

    while True:
        if runtime.process.poll() is not None:
            raise RuntimeError(
                f"Chromium exited unexpectedly with code {runtime.process.returncode}."
            )

        if await _linkedin_login_saved(runtime.context):
            print("LINKEDIN_LOGIN_SAVED")
            print(f"Current URL: {runtime.page.url}")
            # Give Chromium a moment to flush profile state before shutdown.
            await asyncio.sleep(5)
            return

        await asyncio.sleep(2)


async def main() -> int:
    runtime = None
    async with async_playwright() as playwright:
        try:
            runtime = await launch_application_browser(playwright)
            print("PLAYWRIGHT_ATTACHED")
            print(f"Profile: {runtime.browser_profile_path}")

            if not await _linkedin_login_saved(runtime.context):
                try:
                    await runtime.page.goto(
                        LINKEDIN_LOGIN_URL,
                        wait_until="domcontentloaded",
                        timeout=120_000,
                    )
                except Exception as exc:
                    print(f"LinkedIn navigation warning: {exc}")

            await _wait_for_saved_login(runtime)
            return 0
        finally:
            if runtime is not None:
                runtime.terminate(remove_profile=False)


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nLogin helper cancelled. The dedicated profile was preserved.")
        sys.exit(130)
