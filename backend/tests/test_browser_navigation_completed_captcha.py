from __future__ import annotations

import os

import pytest

from app.services.browser_navigation import detect_blocking_challenge


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("widget_html", "response_selector"),
    [
        (
            '<iframe src="https://www.google.com/recaptcha/api2/anchor"></iframe>'
            '<textarea name="g-recaptcha-response"></textarea>',
            'textarea[name="g-recaptcha-response"]',
        ),
        (
            '<iframe src="https://newassets.hcaptcha.com/captcha/v1/index.html"></iframe>'
            '<textarea name="h-captcha-response"></textarea>',
            'textarea[name="h-captcha-response"]',
        ),
        (
            '<div id="captcha-widget"></div>'
            '<input name="cf-turnstile-response">',
            'input[name="cf-turnstile-response"]',
        ),
    ],
)
async def test_completed_captcha_token_suppresses_stale_widget_detection(
    widget_html: str,
    response_selector: str,
) -> None:
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        await playwright.stop()
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required for CAPTCHA resume testing: {exc}")
        pytest.skip("Chromium is not installed in this environment")

    page = await browser.new_page()
    try:
        await page.set_content(
            f"""
            <form class="application-form">
              <input type="file">
              <input type="email" value="synthetic@example.invalid">
              {widget_html}
              <button type="submit">Submit application</button>
            </form>
            """
        )
        pending = await detect_blocking_challenge(page)
        await page.locator(response_selector).evaluate(
            "(element) => { element.value = 'x'.repeat(64); }"
        )
        completed = await detect_blocking_challenge(page)
    finally:
        await browser.close()
        await playwright.stop()

    assert pending is not None
    assert pending["reason_code"] == "captcha_detected"
    assert completed is None
