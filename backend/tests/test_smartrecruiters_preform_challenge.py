import os

import pytest
import pytest_asyncio

# Importing the registry installs the narrow SmartRecruiters challenge classifier.
from app.services import ats_flow
from app.services.ats_registry import detect_ats_adapter


@pytest_asyncio.fixture
async def browser_page():
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    browser = None
    context = None
    try:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as exc:
            if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
                pytest.fail(f"Chromium is required for DataDome certification: {exc}")
            pytest.skip("Chromium is not installed in this environment")
        context = await browser.new_context()
        page = await context.new_page()
        yield page
    finally:
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_smartrecruiters_datadome_is_classified_as_preform_manual_handoff(browser_page):
    await browser_page.set_content(
        """
        <main>
          <iframe
            src="https://geo.captcha-delivery.com/captcha/?cid=fixture"
            title="Security verification"
          ></iframe>
        </main>
        """
    )

    adapter = await detect_ats_adapter(
        browser_page,
        "https://jobs.smartrecruiters.com/oneclick-ui/company/Example/publication/fixture",
    )
    assert adapter.name == "smartrecruiters"

    challenge = await ats_flow.detect_blocking_challenge(browser_page)
    assert challenge is not None
    assert challenge["reason_code"] == "anti_bot_challenge"
    assert challenge["details"]["provider"] == "datadome"
    assert challenge["details"]["platform"] == "smartrecruiters"
    assert challenge["details"]["handoff_boundary"] == "pre_form"
    assert challenge["details"]["bypass_attempted"] is False


@pytest.mark.asyncio
async def test_unrelated_iframe_is_not_misclassified_as_datadome(browser_page):
    await browser_page.set_content(
        '<iframe src="https://example.org/ordinary-application-frame"></iframe>'
    )
    challenge = await ats_flow.detect_blocking_challenge(browser_page)
    assert challenge is None
