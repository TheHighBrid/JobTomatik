from __future__ import annotations

import os

import pytest

# Importing the compatibility surface installs the strict Lever challenge detector
# before the browser-navigation function is exercised.
from app.services import form_filler as _form_filler  # noqa: F401
from app.services import browser_navigation


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("widget_html", "response_selector"),
    [
        (
            '<iframe src="https://www.google.com/recaptcha/api2/anchor?size=normal" '
            'style="width:304px;height:78px"></iframe>'
            '<textarea name="g-recaptcha-response" style="display:none"></textarea>',
            'textarea[name="g-recaptcha-response"]',
        ),
        (
            '<iframe src="https://newassets.hcaptcha.com/captcha/v1/index.html?size=normal" '
            'style="width:303px;height:78px"></iframe>'
            '<textarea name="h-captcha-response" style="display:none"></textarea>',
            'textarea[name="h-captcha-response"]',
        ),
        (
            '<div id="captcha-widget" style="width:300px;height:70px">Verify you are human</div>'
            '<input name="cf-turnstile-response" style="display:none">',
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
        pending = await browser_navigation.detect_blocking_challenge(page)
        await page.locator(response_selector).evaluate(
            "(element) => { element.value = 'x'.repeat(64); }"
        )
        completed = await browser_navigation.detect_blocking_challenge(page)
    finally:
        await browser.close()
        await playwright.stop()

    assert pending is not None
    assert pending["reason_code"] == "captcha_detected"
    assert pending["details"]["visible"] is True
    assert completed is None


@pytest.mark.asyncio
async def test_invisible_captcha_plumbing_and_legal_text_do_not_create_handoff() -> None:
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        await playwright.stop()
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required for CAPTCHA visibility testing: {exc}")
        pytest.skip("Chromium is not installed in this environment")

    page = await browser.new_page()
    try:
        await page.set_content(
            """
            <form class="application-form">
              <input type="file">
              <input type="email" value="synthetic@example.invalid">
              <div class="grecaptcha-badge" style="width:256px;height:60px">
                <iframe
                  src="https://www.google.com/recaptcha/api2/anchor?size=invisible"
                  style="width:256px;height:60px"
                ></iframe>
              </div>
              <textarea name="g-recaptcha-response" style="display:none"></textarea>
              <p>This site is protected by reCAPTCHA and the Google Privacy Policy applies.</p>
              <button type="submit">Submit application</button>
            </form>
            """
        )
        challenge = await browser_navigation.detect_blocking_challenge(page)
    finally:
        await browser.close()
        await playwright.stop()

    assert challenge is None
