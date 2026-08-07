from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest

from app.services.employer_application_entry import continue_from_employer_landing


DESJARDINS_LIVE_URL = (
    "https://desjardins-workplace.relevance.studio/en/job-detail/"
    "1-8be45c6a3a60100201e72dd7efbe0001-fraud-prevention-advisor-remote-montreal"
)


@pytest.mark.asyncio
async def test_live_desjardins_apply_reaches_certified_workday_entry_without_handoff():
    if os.getenv("RUN_DESJARDINS_LIVE_SMOKE") != "1":
        pytest.skip("Desjardins live doorway smoke is opt-in")

    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    browser = None
    try:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(DESJARDINS_LIVE_URL, wait_until="domcontentloaded", timeout=45000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # The live page must still expose an ordinary Apply doorway. The resolver may
        # follow the job-matched Workday target already serialized in the page instead
        # of changing the user's cookie preferences merely to make pointer clicking
        # possible under a consent overlay.
        visible_apply_count = await page.locator(
            'button:has-text("Apply"),a:has-text("Apply"),[role="button"]:has-text("Apply")'
        ).count()
        assert visible_apply_count >= 1
        body_text = await page.locator("body").inner_text()
        assert "R2511328" in body_text

        log = []
        result = await continue_from_employer_landing(
            page,
            source_url=DESJARDINS_LIVE_URL,
            log=log,
            max_steps=3,
            settle_timeout_seconds=15.0,
        )

        assert result, f"No safe application target found. log={log!r}"
        assert result.get("trusted_ats_adapter") == "workday", (
            f"Expected Desjardins to reach hosted Workday. result={result!r} log={log!r}"
        )
        application_url = str(result.get("application_url") or "")
        parsed_application_url = urlparse(application_url)
        application_host = (parsed_application_url.hostname or "").lower()
        assert parsed_application_url.scheme == "https"
        assert application_host == "myworkdayjobs.com" or application_host.endswith(
            ".myworkdayjobs.com"
        )
        assert result.get("application_form_detected") is False

        actions = [entry.get("action") for entry in log]
        assert "intermediate_employer_embedded_ats_target_found" in actions
        assert "intermediate_employer_embedded_ats_navigated" in actions
        assert "intermediate_employer_trusted_ats_reached" in actions
        assert not any("handoff" in str(action or "") for action in actions)
    finally:
        if browser is not None:
            await browser.close()
        await playwright.stop()
