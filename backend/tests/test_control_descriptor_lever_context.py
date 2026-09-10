import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio

from app.services.control_descriptors import element_descriptor
from app.services.control_policy import classify_control_question


FIXTURE = Path(__file__).parent / "fixtures" / "lever_phase_b_descriptor_specimens.html"


class _LeverRadioElement:
    async def evaluate(self, script):
        # Fast source-level guard for the historical hosted Lever wrapper.
        assert ".application-question" in script
        assert ":scope > label" in script
        return (
            "cards[c3a70b5e-ccc1-4d86-b4f6-4c206aa203e0][field0] | Yes | "
            "Are you physically located in Canada and legally authorized to work in Canada for any employer?"
        )


def test_lever_radio_descriptor_retains_human_question_context():
    descriptor = asyncio.run(element_descriptor(None, _LeverRadioElement()))

    assert "cards[c3a70b5e-ccc1-4d86-b4f6-4c206aa203e0][field0]" in descriptor
    assert "legally authorized to work in Canada" in descriptor
    assert classify_control_question(descriptor)["canonical_key"] == "work_authorization"


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
async def test_phase_b_257_258_sanitized_html_retains_human_prompts(page):
    """Prove the 257/258 opaque-card failure shapes against a real DOM engine."""
    await page.set_content(FIXTURE.read_text(encoding="utf-8"))

    cases = {
        "dialog-salary": "What is your target base salary range?",
        "dialog-auth": "Are you legally authorized to work in the Country in which this position is located?",
        "dialog-prior": "Have you worked for DIALOG in the past?",
        "dialog-location": "Are you currently located in the city or surrounding area where this position is based?",
        "dialog-hybrid": "DIALOG operates in a hybrid work environment",
        "dialog-source": "How did you hear about us?",
        "dialog-clearance": "This role requires Level 2 clearance",
        "policyme-canada": "Are you based in Canada?",
        "policyme-interest": "In 3-5 sentences, please explain why you are interested in this role?",
        "policyme-french": "Do you speak french?",
        "policyme-insurance": "Do you have experience in the insurance industry?",
        "policyme-salary": "What is your expected salary range? (Total compensation)",
        "policyme-source": "How did you hear about this opportunity?",
    }

    for case, expected_prompt in cases.items():
        element = await page.query_selector(f'[data-case="{case}"]')
        assert element is not None, case
        descriptor = await element_descriptor(page, element)
        assert expected_prompt in descriptor, f"{case}: {descriptor}"
        assert "cards[" in descriptor, f"fixture no longer reproduces opaque identity for {case}"

    auth = await page.query_selector('[data-case="dialog-auth"]')
    auth_descriptor = await element_descriptor(page, auth)
    assert classify_control_question(auth_descriptor)["canonical_key"] == "work_authorization"


@pytest.mark.asyncio
async def test_opaque_card_fallback_does_not_mistake_option_text_for_prompt(page):
    await page.set_content(
        """
        <div class="lever-card">
          <div class="prompt">Are you based in Canada?</div>
          <div>
            <label><input data-case="target" type="radio"
              name="cards[00000000-0000-0000-0000-000000000000][field0]"
              value="No" required>No</label>
            <label><input type="radio"
              name="cards[00000000-0000-0000-0000-000000000000][field0]"
              value="Yes">Yes</label>
          </div>
        </div>
        """
    )
    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert "Are you based in Canada?" in descriptor
    assert descriptor != "cards[00000000-0000-0000-0000-000000000000][field0] | No"
