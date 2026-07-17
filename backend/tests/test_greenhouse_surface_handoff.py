import os

import pytest
import pytest_asyncio

from app.services.ats_flow import run_ats_application_flow
from app.services.ats_greenhouse import GreenhouseAdapter
from app.services.form_filler_v3 import _fill_step_fields


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
            pytest.fail(f"Chromium is required for Greenhouse certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_direct_greenhouse_form_wins_over_application_titled_proxy_iframe(page):
    await page.set_content(
        """
        <form id="application_form" action="https://boards.greenhouse.io/acme/jobs/123">
          <button id="submit_app" type="submit">Submit Application</button>
        </form>
        <iframe title="application helper" srcdoc="<p>proxy helper</p>"></iframe>
        """
    )

    surface = await GreenhouseAdapter().resolve_surface(page)

    assert surface is page
    assert await surface.query_selector("#application_form") is not None
    assert await surface.query_selector("#submit_app") is not None


@pytest.mark.asyncio
async def test_passive_captcha_is_recorded_after_safe_fill_and_upload(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nGreenhouse synthetic certification resume")

    await page.set_content(
        """
        <form id="application_form" action="https://boards.greenhouse.io/acme/jobs/123">
          <label for="first">First Name</label>
          <input id="first" name="first_name" required>
          <label for="last">Last Name</label>
          <input id="last" name="last_name" required>
          <label for="email">Email</label>
          <input id="email" name="email" type="email" required>
          <label for="resume">Resume</label>
          <input id="resume" name="resume" type="file" accept=".pdf" required>
          <button id="submit_app" type="submit">Submit Application</button>
        </form>
        <iframe title="reCAPTCHA" src="about:blank?recaptcha"></iframe>
        <script>
          document.querySelector('#application_form').onsubmit = (event) => event.preventDefault();
        </script>
        """
    )

    profile = {
        "first_name": "Avery",
        "last_name": "Certification",
        "full_name": "Avery Certification",
        "email": "avery.certification@example.test",
        "answer_policies": [],
    }
    adapter = GreenhouseAdapter()
    log = []

    async def fill_step(surface, step_number):
        return await _fill_step_fields(
            surface,
            profile=profile,
            cover_letter="Synthetic certification only.",
            resume_path=str(resume),
            log=log,
            step_number=step_number,
        )

    result = await run_ats_application_flow(
        page,
        adapter,
        fill_step=fill_step,
        dry_run=True,
        log=log,
    )

    assert result.success is False
    assert result.ready_to_submit is False
    assert result.requires_manual_review is True
    assert result.fields_filled >= 4
    assert result.upload_evidence[0]["verification"] == "passed"
    captcha = next(
        item for item in result.review_items
        if item.get("reason_code") == "captcha_detected"
    )
    assert captcha["details"]["handoff_stage"] == "post_fill_pre_action"
    assert captcha["details"]["fields_filled"] >= 4
    assert captcha["details"]["upload_evidence_count"] >= 1
    assert captcha["details"]["submit_clicked"] is False
    assert any(
        item.get("action") == "captcha_widget_deferred_until_manual_handoff"
        for item in log
    )
    assert any(item.get("action") == "ats_manual_challenge_ready" for item in log)
    assert not any(item.get("action") == "ats_submit_clicked" for item in log)
