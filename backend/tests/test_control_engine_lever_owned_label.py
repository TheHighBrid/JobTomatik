import os

import pytest
import pytest_asyncio

from app.services.answer_policy import resolve_runtime_policy
from app.services.control_descriptors import element_descriptor
from app.services.control_native import choice_option


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
    """Opaque answer labels stay option data and cannot enter question classification."""
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
    option = await choice_option(page, element, 0)

    assert opaque_name in descriptor
    assert "Please contact me" not in descriptor
    assert "How did you hear about us?" in descriptor
    assert option.label == "Please contact me"
    assert option.value == "Please contact me"


@pytest.mark.asyncio
async def test_opaque_choice_answer_cannot_cross_bind_legal_policy(page):
    """Legal-looking answer text cannot classify an unrelated opaque employer question."""
    opaque_name = "cards[18181818-1818-1818-1818-181818181818][field0]"
    await page.set_content(
        f"""
        <div class="lever-card">
          <div>Which contact preference do you want?</div>
          <div>
            <input id="legal-looking" data-case="target" type="radio"
              name="{opaque_name}" value="legal-looking-option" required>
            <label for="legal-looking">I am legally authorized to work in Canada</label>
            <input id="none" type="radio" name="{opaque_name}" value="none">
            <label for="none">No preference</label>
          </div>
        </div>
        """
    )

    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)
    option = await choice_option(page, element, 0)
    resolved = resolve_runtime_policy(
        descriptor,
        [{"id": 1, "canonical_key": "work_authorization", "scope": "global"}],
    )

    assert "Which contact preference do you want?" in descriptor
    assert "legally authorized" not in descriptor.lower()
    assert option.label == "I am legally authorized to work in Canada"
    assert resolved["canonical_key"] != "work_authorization"
    assert resolved["matched"] is False
    assert resolved["can_autofill"] is False


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
    assert "Please contact me" not in descriptor
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


@pytest.mark.asyncio
async def test_mixed_structured_and_unstructured_prompts_fail_closed(page):
    """A styled prompt cannot outrank a conflicting plausible unstructured sibling."""
    opaque_name = "cards[19191919-1919-1919-1919-191919191919][field0]"
    await page.set_content(
        f"""
        <div class="lever-card">
          <div class="question-label">Are you legally authorized to work in Canada?</div>
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


@pytest.mark.asyncio
async def test_multi_token_aria_role_is_foreign_ownership_boundary(page):
    """ARIA fallback-role tokens cannot disappear from opaque ownership checks."""
    opaque_name = "cards[20202020-2020-2020-2020-202020202020][field0]"
    await page.set_content(
        f"""
        <div class="application-question">
          <div class="question-label">Are you legally authorized to work in Canada?</div>
          <div><input data-case="target" name="{opaque_name}" required></div>
          <div role="switch checkbox" aria-label="Foreign fallback widget"></div>
        </div>
        """
    )

    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert descriptor == opaque_name
    assert "legally authorized" not in descriptor


@pytest.mark.asyncio
async def test_same_name_choices_in_sibling_group_are_foreign_ownership(page):
    """Same-name same-kind choices in another structural group are not one question."""
    opaque_name = "cards[21212121-2121-2121-2121-212121212121][field0]"
    await page.set_content(
        f"""
        <div class="application-question">
          <div class="question-label">Are you legally authorized to work in Canada?</div>
          <fieldset data-case="target-group">
            <label><input type="radio" name="{opaque_name}" value="Yes" required>Yes</label>
            <label><input type="radio" name="{opaque_name}" value="No">No</label>
          </fieldset>
          <fieldset>
            <label><input type="radio" name="{opaque_name}" value="Maybe">Maybe</label>
            <label><input type="radio" name="{opaque_name}" value="Later">Later</label>
          </fieldset>
        </div>
        """
    )

    group = await page.query_selector('[data-case="target-group"]')
    descriptor = await element_descriptor(page, group)

    assert descriptor == opaque_name
    assert "legally authorized" not in descriptor
