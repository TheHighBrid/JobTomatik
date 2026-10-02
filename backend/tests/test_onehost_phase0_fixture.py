"""Phase 0 proof: JobTomatik owns the browser process.

This is the locked recovery gate. It launches Chromium, fills a local fixture,
writes a Playwright trace, and shuts down. It does not attach over CDP, open an
employer site, submit, or touch Android.
"""

import os
from pathlib import Path

import pytest
import pytest_asyncio

FIXTURE = Path(__file__).parent / "fixtures" / "onehost_phase0_form.html"


@pytest_asyncio.fixture
async def owned_browser():
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    launch_kwargs = {"headless": True}
    executable = os.getenv("JOBTOMATIK_CHROMIUM")
    if executable:
        launch_kwargs["executable_path"] = executable
    try:
        browser = await playwright.chromium.launch(**launch_kwargs)
    except Exception as exc:
        await playwright.stop()
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required for the OneHost phase 0 proof: {exc}")
        pytest.skip(f"Chromium is not installed in this environment: {exc}")
    try:
        yield browser
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_onehost_phase0_owned_chromium_fills_local_fixture(owned_browser, tmp_path):
    assert owned_browser.browser_type.name == "chromium"

    context = await owned_browser.new_context()
    trace_path = tmp_path / "onehost-phase0-trace.zip"
    await context.tracing.start(screenshots=True, snapshots=True)
    page = await context.new_page()
    await page.goto(FIXTURE.resolve().as_uri())
    await page.locator("#first").fill("Phase Zero")
    await page.locator("#email").fill("phase0@example.test")
    await page.locator("#auth").select_option("yes")

    assert await page.locator("#first").input_value() == "Phase Zero"
    assert await page.locator("#email").input_value() == "phase0@example.test"
    assert await page.locator("#auth").input_value() == "yes"
    assert await page.evaluate("() => window.__jobtomatikSubmitClicked") is False

    await context.tracing.stop(path=str(trace_path))
    await context.close()

    assert trace_path.is_file()
    assert trace_path.stat().st_size > 100
