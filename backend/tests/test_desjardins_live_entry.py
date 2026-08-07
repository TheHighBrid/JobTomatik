from __future__ import annotations

import os

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

        apply_dom = await page.locator('a,button,[role="button"],input[type="button"]').evaluate_all(
            """els => els
              .filter(el => /apply/i.test([
                el.innerText || '', el.value || '', el.getAttribute('aria-label') || ''
              ].join(' ')))
              .slice(0, 12)
              .map(el => ({
                tag: el.tagName,
                text: (el.innerText || el.value || '').trim(),
                ariaLabel: el.getAttribute('aria-label'),
                href: el.getAttribute('href'),
                type: el.getAttribute('type'),
                role: el.getAttribute('role'),
                target: el.getAttribute('target'),
                dataHref: el.getAttribute('data-href'),
                dataUrl: el.getAttribute('data-url'),
                outerHTML: el.outerHTML.slice(0, 1200),
              }))"""
        )

        log = []
        result = await continue_from_employer_landing(
            page,
            source_url=DESJARDINS_LIVE_URL,
            log=log,
            max_steps=3,
            settle_timeout_seconds=15.0,
        )

        context_urls = [candidate.url for candidate in page.context.pages]
        assert result, (
            f"No safe application target found. log={log!r} "
            f"apply_dom={apply_dom!r} context_urls={context_urls!r}"
        )
        assert result.get("trusted_ats_adapter") == "workday", (
            f"Expected Desjardins Apply to reach hosted Workday. "
            f"result={result!r} log={log!r} apply_dom={apply_dom!r} "
            f"context_urls={context_urls!r}"
        )
        assert "myworkdayjobs.com" in str(result.get("application_url") or "")
        assert result.get("application_form_detected") is False
        actions = [entry.get("action") for entry in log]
        assert "intermediate_employer_apply_started" in actions
        assert "intermediate_employer_trusted_ats_reached" in actions
        assert not any("handoff" in str(action or "") for action in actions)
    finally:
        if browser is not None:
            await browser.close()
        await playwright.stop()
