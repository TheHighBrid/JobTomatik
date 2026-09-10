import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio

from app.services.control_descriptors import element_descriptor
from app.services.control_engine import fill_policy_controls
from app.services.control_policy import classify_control_question


FIXTURE = Path(__file__).parent / "fixtures" / "lever_phase_b_descriptor_specimens.html"


class _LeverRadioElement:
    async def evaluate(self, script):
        # Fast source-level guard for the historical hosted Lever wrapper.
        assert ".application-question" in script
        assert "OPAQUE_CARD_RE" in script
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
        "dialog-salary": "Base salary is one aspect of your total rewards package. What is your target base salary range?",
        "dialog-auth": "Are you legally authorized to work in the Country in which this position is located?",
        "dialog-prior": "Have you worked for DIALOG in the past?",
        "dialog-location": "Are you currently located in the city or surrounding area where this position is based?",
        "dialog-hybrid": "DIALOG operates in a hybrid work environment, with team members collaborating at least three days per week in the studio. We believe this approach helps foster creativity and connection. Does this work for you?",
        "dialog-source": "How did you hear about us?",
        "dialog-clearance": "This role requires Level 2 clearance. A background check for the past ten years will need to be completed. Do you see any concerns with this?",
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


@pytest.mark.asyncio
async def test_opaque_card_fallback_skips_descriptive_answer_labels(page):
    """A radio option such as Career Fair must not terminate prompt recovery."""
    await page.set_content(
        """
        <div class="lever-card">
          <div>How did you hear about us?</div>
          <div>
            <label><input data-case="target" type="radio"
              name="cards[22222222-2222-2222-2222-222222222222][field0]"
              value="Career Fair" required>Career Fair</label>
            <label><input type="radio"
              name="cards[22222222-2222-2222-2222-222222222222][field0]"
              value="Referral">Referral</label>
          </div>
        </div>
        """
    )
    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert "Career Fair" in descriptor
    assert "How did you hear about us?" in descriptor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt",
    [
        "Desired salary range",
        "Please describe your relevant experience",
    ],
)
async def test_opaque_card_fallback_retains_statement_style_prompts(page, prompt):
    """Valid employer prompts do not need to end in a question mark."""
    await page.set_content(
        f"""
        <div class="lever-card">
          <div>{prompt}</div>
          <div>
            <input data-case="target"
              name="cards[33333333-3333-3333-3333-333333333333][field0]" required>
          </div>
        </div>
        """
    )
    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert prompt in descriptor


@pytest.mark.asyncio
async def test_compound_application_questionnaire_cannot_cross_bind_neighbor_prompt(page):
    """Plural/compound outer wrappers may not donate another field's prompt."""
    await page.set_content(
        """
        <div class="job-application-questionnaire">
          <label>Are you legally authorized to work in Canada?</label>
          <div class="lever-card">
            <div>Desired salary range</div>
            <div>
              <input data-case="target"
                name="cards[44444444-4444-4444-4444-444444444444][field0]" required>
            </div>
          </div>
          <div class="lever-card">
            <div>Do you speak French?</div>
            <div>
              <input name="cards[55555555-5555-5555-5555-555555555555][field0]" required>
            </div>
          </div>
        </div>
        """
    )
    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert "Desired salary range" in descriptor
    assert "legally authorized" not in descriptor
    assert "Do you speak French?" not in descriptor


@pytest.mark.asyncio
async def test_opaque_card_fallback_stops_before_multi_question_container(page):
    """If local prompt evidence is absent, another cards[...] field stops ancestor recovery."""
    await page.set_content(
        """
        <div>
          <div>Desired salary range</div>
          <div><input data-case="target"
            name="cards[66666666-6666-6666-6666-666666666666][field0]" required></div>
          <div><input
            name="cards[77777777-7777-7777-7777-777777777777][field0]" required></div>
        </div>
        """
    )
    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert "Desired salary range" not in descriptor
    assert descriptor == "cards[66666666-6666-6666-6666-666666666666][field0]"


@pytest.mark.asyncio
async def test_opaque_card_fallback_rejects_conventionally_named_sibling_field(page):
    """A normal sibling field is also a hard ownership boundary for opaque cards."""
    await page.set_content(
        """
        <div class="compound-wrapper">
          <label for="auth">Are you legally authorized to work in Canada?</label>
          <input id="auth" name="workAuthorization">
          <div>
            <input data-case="target"
              name="cards[88888888-8888-8888-8888-888888888888][field0]" required>
          </div>
        </div>
        """
    )
    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert "legally authorized" not in descriptor
    assert descriptor == "cards[88888888-8888-8888-8888-888888888888][field0]"


@pytest.mark.asyncio
async def test_choice_group_container_derives_single_opaque_field_prompt_in_engine(page):
    """Exercise the real choice-group path where the descriptor subject is a fieldset."""
    opaque_name = "cards[99999999-9999-9999-9999-999999999999][field0]"
    await page.set_content(
        f"""
        <form>
          <div class="lever-card">
            <div>How did you hear about us?</div>
            <fieldset>
              <label><input type="radio" name="{opaque_name}" value="Career Fair" required>Career Fair</label>
              <label><input type="radio" name="{opaque_name}" value="Referral">Referral</label>
            </fieldset>
          </div>
        </form>
        """
    )

    outcome = await fill_policy_controls(page, [])

    assert outcome.filled_count == 0
    assert len(outcome.review_items) == 1
    descriptor = outcome.review_items[0]["details"]["descriptor"]
    assert opaque_name in descriptor
    assert "How did you hear about us?" in descriptor
    assert not await page.locator(f'input[name="{opaque_name}"][value="Career Fair"]').is_checked()
    assert not await page.locator(f'input[name="{opaque_name}"][value="Referral"]').is_checked()


@pytest.mark.asyncio
async def test_opaque_card_fallback_does_not_bind_unrelated_section_heading(page):
    """If no local question can be proven, keep the opaque descriptor and fail closed."""
    await page.set_content(
        """
        <section>
          <div>CS Application Questions</div>
          <div>
            <label><input data-case="target" type="radio"
              name="cards[11111111-1111-1111-1111-111111111111][field0]"
              value="Yes" required>Yes</label>
            <label><input type="radio"
              name="cards[11111111-1111-1111-1111-111111111111][field0]"
              value="No">No</label>
          </div>
        </section>
        """
    )
    element = await page.query_selector('[data-case="target"]')
    descriptor = await element_descriptor(page, element)

    assert "CS Application Questions" not in descriptor
    assert descriptor == "cards[11111111-1111-1111-1111-111111111111][field0] | Yes"
