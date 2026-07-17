import os

import pytest
import pytest_asyncio

# Importing the public entrypoint installs the Greenhouse compatibility wrappers.
from app.services import form_filler as _form_filler  # noqa: F401
from app.services.control_engine import element_descriptor, fill_policy_controls
from app.services.greenhouse_phone_widget import _reconcile_phone_review


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
            pytest.fail(f"Chromium is required for Greenhouse compatibility tests: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def _policy(answer: str, phrase: str):
    return {
        "id": 9201,
        "canonical_key": "custom.batch02_answer",
        "category": "synthetic_certification",
        "sensitivity": "synthetic",
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "match_phrases": [phrase],
        "scope": "platform",
        "scope_value": "greenhouse",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-17T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_descriptor_only_text_phone_is_semantically_reconciled(page):
    await page.set_content(
        """
        <label for="opaque-field">Phone</label>
        <input id="opaque-field" name="question_123" type="text" required
               value="+1 (613) 555-0199">
        """
    )
    element = await page.query_selector("#opaque-field")
    descriptor = await element_descriptor(page, element)
    review_items = [{
        "reason_code": "unsupported_control",
        "summary": f"Profile field could not be verified: {descriptor}",
        "details": {
            "canonical_key": "profile.phone",
            "category": "profile",
            "descriptor": descriptor,
            "control_type": "text",
            "required": True,
        },
    }]
    log = []
    profile = {
        "full_name": "Avery Certification",
        "first_name": "Avery",
        "last_name": "Certification",
        "email": "avery.certification@example.test",
        "phone": "6135550199",
        "answer_policies": [],
    }

    count = await _reconcile_phone_review(
        page,
        profile=profile,
        cover_letter="",
        log=log,
        review_items=review_items,
    )

    assert descriptor == "question_123 | opaque-field | Phone"
    assert count == 1
    assert review_items == []
    assert log[-1]["action"] == "phone_format_verified"
    assert log[-1]["verified"] is True


@pytest.mark.asyncio
async def test_combobox_resolves_css_special_aria_controls_id_by_exact_dom_id(page):
    await page.set_content(
        """
        <div class="application-field">
          <label id="answer-label">Will you require sponsorship?</label>
          <button id="answer-control" type="button" role="combobox"
                  aria-labelledby="answer-label"
                  aria-controls="question_68078354[]-listbox"
                  aria-expanded="false" aria-required="true">Choose</button>
          <div id="question_68078354[]-listbox" role="listbox" hidden>
            <div id="answer-no" role="option" aria-selected="false">No</div>
            <div id="answer-yes" role="option" aria-selected="false">Yes</div>
          </div>
        </div>
        <script>
          const button = document.getElementById('answer-control');
          const list = document.getElementById('question_68078354[]-listbox');
          button.addEventListener('click', () => {
            list.hidden = false;
            button.setAttribute('aria-expanded', 'true');
          });
          list.querySelectorAll('[role=option]').forEach((option) => {
            option.addEventListener('click', () => {
              option.setAttribute('aria-selected', 'true');
              button.textContent = option.textContent;
              button.setAttribute('aria-expanded', 'false');
              list.hidden = true;
            });
          });
          document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
              list.hidden = true;
              button.setAttribute('aria-expanded', 'false');
            }
          });
        </script>
        """
    )

    outcome = await fill_policy_controls(
        page,
        [_policy("No", "Will you require sponsorship?")],
        [],
    )

    assert await page.locator("#answer-control").inner_text() == "No"
    assert outcome.filled_count == 1
    assert outcome.review_items == []
    assert len(outcome.evidence) == 1
