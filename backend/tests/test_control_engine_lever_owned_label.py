import os

import pytest
import pytest_asyncio

from app.services.control_descriptors import element_descriptor


@pytest_asyncio.fixture
async def page():
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        await playwright.stop()
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required for Lever descriptor certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")

    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_prompt_like_label_for_answer_does_not_stop_prompt_recovery(page):
    """Prompt-like answer text may remain context but must not hide the employer prompt."""
    opaque_name = "cards[12121212-1212-1212-1212-121212121212][field0]"
    await page.set_content(
        f"""
        <div class="lever-card">
          <div>How did you hear about us?</div>
          <div>
            <input id="contact" data-case="target" type="radio"
              name="{opaque_name}" value="Please contact me" required>
            <label for="contact">Please contact me</label>
            <input id="other" type="radio" name="{opaque_name}" value="Other">
            <label for="other">Other</label>
          </div>
        </div>
        """
    )

    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert opaque_name in descriptor
    assert "Please contact me" in descriptor
    assert "How did you hear about us?" in descriptor
