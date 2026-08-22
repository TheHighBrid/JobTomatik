from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.services.browser_runtime import probe_external_playwright_cdp


async def main() -> int:
    settings = get_settings()
    endpoint = (settings.application_browser_cdp_endpoint or "").strip()
    if not endpoint:
        raise RuntimeError(
            "APPLICATION_BROWSER_CDP_ENDPOINT is empty. Set it to "
            "http://127.0.0.1:9222 in backend/.env."
        )

    proof = await probe_external_playwright_cdp(endpoint)
    print("ANDROID_BROWSER_CDP_CONNECTED")
    print(f"Endpoint: {proof['cdp_endpoint']}")
    print(f"Contexts: {proof['context_count']}")
    print(f"Pages: {proof['page_count']}")
    print(f"Multiple pages present: {proof['multiple_pages_present']}")
    print(f"Browser owned by JobTomatik: {proof['browser_owned_by_jobtomatik']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
