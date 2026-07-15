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
            pytest.fail(f"Chromium is required for ATS flow certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_filled_values_cannot_masquerade_as_step_navigation(page):
    await page.set_content(
        """
        <form id="application_form">
          <label for="first">First Name</label>
          <input id="first" required>
          <button id="next" type="button">Next</button>
        </form>
        <script>
          document.querySelector('#next').onclick = () => {};
        </script>
        """
    )
    adapter = GreenhouseAdapter()
    log = []

    async def fill_step(surface, step_number):
        await surface.locator("#first").fill("Candidate")
        return {
            "filled_count": 1,
            "review_items": [],
            "control_evidence": [],
            "upload_evidence": [],
        }

    result = await run_ats_application_flow(
        page,
        adapter,
        fill_step=fill_step,
        dry_run=True,
        log=log,
    )

    assert result.success is False
    assert result.requires_manual_review is True
    assert result.review_items[0]["reason_code"] == "step_navigation_failed"
    assert "did not advance" in result.error


@pytest.mark.asyncio
async def test_step_evidence_is_copied_to_durable_log(page):
    await page.set_content(
        """
        <form id="application_form">
          <section id="one">
            <button id="next" type="button">Next</button>
          </section>
          <section id="two" hidden>
            <button id="submit_app" type="submit">Submit Application</button>
          </section>
        </form>
        <script>
          document.querySelector('#next').onclick = () => {
            document.querySelector('#one').hidden = true;
            document.querySelector('#two').hidden = false;
          };
          document.querySelector('#application_form').onsubmit = (event) => event.preventDefault();
        </script>
        """
    )
    adapter = GreenhouseAdapter()
    log = []

    async def empty_fill(surface, step_number):
        return {
            "filled_count": 0,
            "review_items": [],
            "control_evidence": [],
            "upload_evidence": [],
        }

    result = await run_ats_application_flow(
        page,
        adapter,
        fill_step=empty_fill,
        dry_run=True,
        log=log,
    )

    assert result.success is True
    assert result.ready_to_submit is True
    actions = [item.get("action") for item in log]
    assert "ats_step_filled" in actions
    assert "ats_step_advanced" in actions
    assert "ats_final_submit_ready" in actions
    assert not any(item.get("action") == "ats_submit_clicked" for item in log)
