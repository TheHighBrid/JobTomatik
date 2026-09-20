from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.services.application_browser_contract import application_browser_contract
from app.services.browser_runtime import probe_external_playwright_cdp


async def main() -> int:
    settings = get_settings()
    contract = application_browser_contract(settings)
    if not contract.endpoint:
        raise RuntimeError(
            "APPLICATION_BROWSER_CDP_ENDPOINT is empty for the selected external browser provider."
        )

    proof = await probe_external_playwright_cdp(contract.endpoint)
    print("ANDROID_BROWSER_CDP_CONNECTED")
    print(f"Provider: {contract.provider}")
    print(f"Endpoint: {proof['cdp_endpoint']}")
    print(f"Contexts: {proof['context_count']}")
    print(f"Pages: {proof['page_count']}")
    print(f"Multiple pages present: {proof['multiple_pages_present']}")
    print(f"Browser owned by JobTomatik: {proof['browser_owned_by_jobtomatik']}")
    if contract.native:
        print(f"Android package: {proof.get('android_package', '')}")
        print(f"Connection identity verified: {proof.get('connection_identity_verified')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
