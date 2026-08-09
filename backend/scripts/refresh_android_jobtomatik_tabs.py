#!/usr/bin/env python3
"""Refresh open JobTomatik frontend tabs after a managed Android runtime update.

A Vite page can remain open across a git pull and keep an older JavaScript module graph
and stale task state in memory. The managed Android updater uses native Chromium over
CDP, so it can safely refresh only JobTomatik localhost tabs without touching LinkedIn,
employer ATS pages, or the authenticated browser profile.

An explicitly saved backend URL remains authoritative unless it points to a loopback
backend that is not deployment-attested while the managed Android API is attested. That
specific stale-local case is recovered to the managed endpoint automatically so an old
manual Uvicorn process cannot silently block exact-runtime shadow evidence.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from playwright.async_api import async_playwright

from app.services.browser_runtime import launch_application_browser


MANAGED_API_URL = "http://127.0.0.1:8010"
API_URL_STORAGE_KEY = "jobtomatik_api_url"
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


def is_loopback_api_url(value: str) -> bool:
    try:
        parsed = urlsplit(str(value or ""))
    except Exception:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}
    )


def runtime_identity_attested(base_url: str, *, timeout: float = 2.0) -> bool:
    url = f"{str(base_url or '').rstrip('/')}/api/system/runtime-identity"
    try:
        request = Request(url, headers={"Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback/operator URL only
            if int(getattr(response, "status", 200)) != 200:
                return False
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return bool(
        isinstance(payload, dict)
        and payload.get("deployment_attested") is True
        and payload.get("matches_expected") is True
        and payload.get("role") == "api"
        and payload.get("submission_authorized") is False
        and payload.get("outreach_authorized") is False
    )


def should_recover_saved_api(saved_api_url: str | None) -> bool:
    saved = str(saved_api_url or "").strip().rstrip("/")
    managed = MANAGED_API_URL.rstrip("/")
    if not saved or saved == managed:
        return False
    if not is_loopback_api_url(saved):
        return False
    if not runtime_identity_attested(MANAGED_API_URL):
        return False
    return not runtime_identity_attested(saved)


async def saved_api_url(page) -> str:
    value = await page.evaluate(
        """({ storageKey }) => {
          try { return localStorage.getItem(storageKey) || ''; } catch (_) { return ''; }
        }""",
        {"storageKey": API_URL_STORAGE_KEY},
    )
    return str(value or "").strip()


async def normalize_frontend_page(page, *, recover_saved_api: bool = False) -> None:
    await page.evaluate(
        """({ stalePrefix, storageKey, managedApiUrl, recoverSavedApi }) => {
          try {
            if (recoverSavedApi) localStorage.setItem(storageKey, managedApiUrl);
            for (let i = sessionStorage.length - 1; i >= 0; i -= 1) {
              const key = sessionStorage.key(i);
              if (key && key.startsWith(stalePrefix)) sessionStorage.removeItem(key);
            }
          } catch (_) {}
        }""",
        {
            "stalePrefix": STALE_SUBMIT_TASK_PREFIX,
            "storageKey": API_URL_STORAGE_KEY,
            "managedApiUrl": MANAGED_API_URL,
            "recoverSavedApi": bool(recover_saved_api),
        },
    )
    await page.reload(wait_until="domcontentloaded", timeout=20_000)


async def main() -> int:
    refreshed = 0
    recovered_saved_api = 0
    async with async_playwright() as playwright:
        runtime = await launch_application_browser(playwright)
        try:
            for context in list(runtime.browser.contexts):
                for page in list(context.pages):
                    if not is_jobtomatik_frontend_url(page.url):
                        continue
                    try:
                        saved = await saved_api_url(page)
                        recover = should_recover_saved_api(saved)
                        await normalize_frontend_page(page, recover_saved_api=recover)
                        refreshed += 1
                        recovered_saved_api += int(recover)
                    except Exception as exc:
                        print(f"ANDROID_FRONTEND_TAB_REFRESH_FAILED url={page.url} error={str(exc)[:160]}")
                        return 1
        finally:
            runtime.terminate(remove_profile=False)

    print(f"ANDROID_FRONTEND_TABS_REFRESHED={refreshed}")
    print(f"ANDROID_FRONTEND_API_DEFAULT={MANAGED_API_URL}")
    print(f"ANDROID_FRONTEND_SAVED_API_RECOVERED={recovered_saved_api}")
    print("ANDROID_FRONTEND_SAVED_API_POLICY=ATTESTATION_AWARE")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
