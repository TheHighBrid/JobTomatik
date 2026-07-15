import os

import pytest
import pytest_asyncio

from app.services.ats_flow import run_ats_application_flow
from app.services.ats_greenhouse import GreenhouseAdapter


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
            pytest.fail(f"Chromium is required for CAPTCHA handoff certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_passive_captcha_is_deferred_until_after_safe_form_fill(page):
    await page.set_content(
        """
        <iframe title="reCAPTCHA" src="about:blank?recaptcha=1" style="width:304px;height:78px"></iframe>
        <form id="application_form">
          <label for="first">First Name</label>
          <input id="first" required>
          <input id="resume" type="file" required>
          <button id="submit_app" type="submit">Submit Application</button>
        </form>
        <script>
          document.querySelector('#application_form').onsubmit = (event) => event.preventDefault();
        </script>
        """
    )
    adapter = GreenhouseAdapter()
    log = []

    async def fill_step(surface, step_number):
        await surface.locator("#first").fill("Avery")
        return {
            "filled_count": 2,
            "review_items": [],
            "control_evidence": [{"control_id": "first", "verification": "passed"}],
            "upload_evidence": [{
                "control_id": "resume",
                "upload_type": "resume",
                "filename": "synthetic-resume.pdf",
                "verification": "passed",
            }],
        }

    result = await run_ats_application_flow(
        page,
        adapter,
        fill_step=fill_step,
        dry_run=True,
        log=log,
    )

    assert await page.locator("#first").input_value() == "Avery"
    assert result.success is False
    assert result.ready_to_submit is False
    assert result.requires_manual_review is True
    assert result.fields_filled == 2
    assert result.steps_completed == 1
    assert result.review_items[0]["reason_code"] == "captcha_detected"
    assert result.review_items[0]["details"]["handoff_stage"] == "post_fill_pre_action"
    assert result.review_items[0]["details"]["submit_clicked"] is False
    actions = [item.get("action") for item in log]
    assert "captcha_widget_deferred_until_manual_handoff" in actions
    assert "ats_step_filled" in actions
    assert "ats_manual_challenge_ready" in actions
    assert "ats_submit_clicked" not in actions
