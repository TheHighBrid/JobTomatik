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

        observed_requests: list[str] = []

        def record_request(request) -> None:
            url = str(request.url or "")
            lowered = url.lower()
            if any(token in lowered for token in (
                "workday",
                "myworkdayjobs",
                "apply",
                "job-detail",
                "relevance.studio",
            )):
                if url not in observed_requests and len(observed_requests) < 40:
                    observed_requests.append(url)

        page.on("request", record_request)

        log = []
        result = await continue_from_employer_landing(
            page,
            source_url=DESJARDINS_LIVE_URL,
            log=log,
            max_steps=3,
            settle_timeout_seconds=15.0,
        )

        context_urls = [candidate.url for candidate in page.context.pages]
        post_controls = await page.locator('a,button,[role="button"],input[type="button"]').evaluate_all(
            """els => els.slice(0, 80).map(el => ({
              tag: el.tagName,
              text: (el.innerText || el.value || '').trim().slice(0, 240),
              href: el.getAttribute('href'),
              type: el.getAttribute('type'),
              role: el.getAttribute('role'),
              ariaLabel: el.getAttribute('aria-label'),
              visible: Boolean(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
            })).filter(item => item.visible)"""
        )
        dialogs = await page.locator('[role="dialog"],dialog,[aria-modal="true"]').evaluate_all(
            """els => els.slice(0, 10).map(el => ({
              text: (el.innerText || el.textContent || '').trim().slice(0, 1200),
              outerHTML: el.outerHTML.slice(0, 1800),
            }))"""
        )
        workday_links = await page.locator('a[href*="myworkdayjobs.com" i]').evaluate_all(
            """els => els.slice(0, 20).map(el => ({
              text: (el.innerText || el.textContent || '').trim().slice(0, 300),
              href: el.href || el.getAttribute('href') || '',
            }))"""
        )
        embedded_workday_urls = await page.evaluate(
            """() => Array.from(new Set(
              (document.documentElement.innerHTML.match(/https?:[^\"'<>\\s]+myworkdayjobs\.com[^\"'<>\\s]*/gi) || [])
            )).slice(0, 20)"""
        )
        body_text = (await page.locator("body").inner_text())[:5000]

        diagnostics = (
            f"apply_dom={apply_dom!r} context_urls={context_urls!r} "
            f"requests={observed_requests!r} post_controls={post_controls!r} "
            f"dialogs={dialogs!r} workday_links={workday_links!r} "
            f"embedded_workday_urls={embedded_workday_urls!r} body={body_text!r}"
        )
        assert result, f"No safe application target found. log={log!r} {diagnostics}"
        assert result.get("trusted_ats_adapter") == "workday", (
            f"Expected Desjardins Apply to reach hosted Workday. "
            f"result={result!r} log={log!r} {diagnostics}"
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
