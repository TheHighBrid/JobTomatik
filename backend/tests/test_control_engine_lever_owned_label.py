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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "foreign_markup",
    [
        '<div role="textbox" aria-label="Foreign textbox"></div>',
        '<button type="button" role="switch" aria-label="Foreign switch"></button>',
        '<div role="listbox" aria-label="Foreign listbox"></div>',
        '<div role="button" tabindex="0">Foreign button</div>',
        '<div contenteditable="true">Foreign editable field</div>',
    ],
)
async def test_foreign_aria_and_editable_widgets_are_ownership_boundaries(page, foreign_markup):
    """Non-native interactive widgets must prevent cross-binding from a shared wrapper."""
    opaque_name = "cards[13131313-1313-1313-1313-131313131313][field0]"
    await page.set_content(
        f"""
        <div class="lever-card">
          <div>Are you legally authorized to work in Canada?</div>
          <div><input data-case="target" name="{opaque_name}" required></div>
          {foreign_markup}
        </div>
        """
    )

    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert "legally authorized" not in descriptor
    assert descriptor == opaque_name


@pytest.mark.asyncio
async def test_direct_named_group_still_requires_single_field_ownership(page):
    """A group carrying cards[...] itself cannot bypass descendant ownership validation."""
    opaque_name = "cards[14141414-1414-1414-1414-141414141414][field0]"
    await page.set_content(
        f"""
        <fieldset data-case="target-group" name="{opaque_name}"
          aria-label="Are you legally authorized to work in Canada?">
          <label><input type="radio" name="{opaque_name}" value="Yes" required>Yes</label>
          <label><input type="radio" name="{opaque_name}" value="No">No</label>
          <input name="notes">
        </fieldset>
        """
    )

    group = await page.query_selector('[data-case="target-group"]')
    descriptor = await element_descriptor(page, group)

    assert descriptor == opaque_name
    assert "legally authorized" not in descriptor


@pytest.mark.asyncio
async def test_nested_owned_answer_label_cannot_become_prompt(page):
    """A label[for] nested in a prompt-like wrapper remains answer context only."""
    opaque_name = "cards[15151515-1515-1515-1515-151515151515][field0]"
    await page.set_content(
        f"""
        <div class="lever-card">
          <div>How did you hear about us?</div>
          <div>
            <div class="prompt"><label for="contact">Please contact me</label></div>
            <input id="contact" data-case="target" type="radio"
              name="{opaque_name}" value="Please contact me" required>
            <input id="other" type="radio" name="{opaque_name}" value="Other">
            <label for="other">Other</label>
          </div>
        </div>
        """
    )

    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert opaque_name in descriptor
    assert "How did you hear about us?" in descriptor


@pytest.mark.asyncio
async def test_derived_group_choice_kind_rejects_same_name_different_choice_kind(page):
    """A derived radio group may not absorb a same-name checkbox in a wider wrapper."""
    opaque_name = "cards[16161616-1616-1616-1616-161616161616][field0]"
    await page.set_content(
        f"""
        <div class="application-question">
          <div class="question-label">Are you legally authorized to work in Canada?</div>
          <fieldset data-case="target-group">
            <label><input type="radio" name="{opaque_name}" value="Yes" required>Yes</label>
            <label><input type="radio" name="{opaque_name}" value="No">No</label>
          </fieldset>
          <label><input type="checkbox" name="{opaque_name}" value="Agree">I agree</label>
        </div>
        """
    )

    group = await page.query_selector('[data-case="target-group"]')
    descriptor = await element_descriptor(page, group)

    assert opaque_name in descriptor
    assert "legally authorized" not in descriptor


@pytest.mark.asyncio
async def test_ambiguous_unstructured_prompts_fail_closed(page):
    """Two plausible prompt siblings cannot be resolved by first-match ordering."""
    opaque_name = "cards[17171717-1717-1717-1717-171717171717][field0]"
    await page.set_content(
        f"""
        <div class="lever-card">
          <div>Are you legally authorized to work in Canada?</div>
          <div>Desired salary range</div>
          <div><input data-case="target" name="{opaque_name}" required></div>
        </div>
        """
    )

    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert descriptor == opaque_name
    assert "legally authorized" not in descriptor
    assert "Desired salary range" not in descriptor
