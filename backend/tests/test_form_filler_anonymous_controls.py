import os

import pytest
import pytest_asyncio

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
            pytest.fail(f"Chromium is required for anonymous-control certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_uploader_subordinate_text_control_is_not_treated_as_question(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nSynthetic")
    await page.set_content(
        """
        <div class="application-field">
          <label for="resume">Resume/CV</label>
          <input id="resume" type="file" required accept=".pdf">
          <textarea required></textarea>
          <span>Attach</span>
        </div>
        """
    )

    outcome = await _fill_step_fields(
        page,
        profile={"answer_policies": []},
        cover_letter="",
        resume_path=str(resume),
        log=[],
        step_number=1,
    )

    assert outcome["review_items"] == []
    assert outcome["upload_evidence"][0]["verification"] == "passed"
    assert await page.locator("#resume").evaluate("(el) => el.files.length") == 1


@pytest.mark.asyncio
async def test_standalone_anonymous_required_text_control_still_blocks(page):
    await page.set_content('<input id="mystery" required>')

    outcome = await _fill_step_fields(
        page,
        profile={"answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert len(outcome["review_items"]) == 1
    review = outcome["review_items"][0]
    assert review["reason_code"] == "ambiguous_question"
    assert review["details"]["descriptor"] == "mystery"
    assert review["details"]["control_metadata"]["id"] == "mystery"
    assert review["details"]["control_metadata"]["hasFileInput"] is False
    assert review["details"]["control_metadata"]["hasCombobox"] is False
