import os

import pytest
import pytest_asyncio

# Importing the public form-filler entrypoint installs the compatibility wrappers.
from app.services import form_filler as _form_filler  # noqa: F401
from app.services.control_engine import fill_policy_controls
from app.services.control_primitives import OptionRecord
from app.services.form_filler_v3 import _fill_step_fields
from app.services.greenhouse_phone_widget import (
    dial_code_option_equivalent,
    phone_values_equivalent,
)


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
            pytest.fail(f"Chromium is required for Greenhouse phone tests: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def _policy(answer: str, phrase: str):
    return {
        "id": 1,
        "canonical_key": "custom.synthetic_phone_country",
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
        "confirmed_at": "2026-07-15T00:00:00Z",
    }


def test_phone_values_accept_formatting_and_country_prefix_only():
    assert phone_values_equivalent("+1 (613) 555-0199", "6135550199") is True
    assert phone_values_equivalent("613-555-0199", "+1 613 555 0199") is True
    assert phone_values_equivalent("5550199", "6135550199") is False
    assert phone_values_equivalent("+44 20 7946 0958", "6135550199") is False


def test_dial_code_verification_requires_matching_code_and_country_label():
    canada = OptionRecord(
        key="canada",
        label="Canada +1",
        value="Canada +1",
        disabled=False,
        selected=False,
    )
    uk = OptionRecord(
        key="uk",
        label="United Kingdom +44",
        value="United Kingdom +44",
        disabled=False,
        selected=False,
    )

    assert dial_code_option_equivalent("+1", canada) is True
    assert dial_code_option_equivalent("+44", canada) is False
    assert dial_code_option_equivalent("+44", uk) is True


@pytest.mark.asyncio
async def test_formatted_phone_value_clears_only_phone_verification_review(page):
    await page.set_content(
        """
        <label for="phone">Phone</label>
        <input id="phone" name="phone" type="tel" required>
        <script>
          document.querySelector('#phone').addEventListener('input', (event) => {
            const digits = event.target.value.replace(/\D/g, '').replace(/^1/, '');
            if (digits.length === 10) {
              event.target.value = `+1 (${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
            }
          });
        </script>
        """
    )
    log = []

    result = await _fill_step_fields(
        page,
        profile={
            "full_name": "Avery Certification",
            "first_name": "Avery",
            "last_name": "Certification",
            "email": "avery.certification@example.test",
            "phone": "6135550199",
            "answer_policies": [],
        },
        cover_letter="",
        resume_path="",
        log=log,
        step_number=1,
    )

    assert await page.locator("#phone").input_value() == "+1 (613) 555-0199"
    assert result["filled_count"] == 1
    assert not any(
        (item.get("details") or {}).get("canonical_key") == "profile.phone"
        for item in result["review_items"]
    )
    assert any(item.get("action") == "phone_format_verified" for item in log)


@pytest.mark.asyncio
async def test_phone_country_selection_can_collapse_to_verified_dial_code(page):
    await page.set_content(
        """
        <label id="phone-country-label">Country Phone</label>
        <button id="phone-country" type="button" role="combobox"
                aria-labelledby="phone-country-label"
                aria-controls="phone-country-list" aria-expanded="false"
                aria-required="true">Choose country</button>
        <div id="phone-country-list" role="listbox" hidden>
          <div id="canada" role="option" aria-selected="false">Canada +1</div>
          <div id="uk" role="option" aria-selected="false">United Kingdom +44</div>
        </div>
        <script>
          const button = document.querySelector('#phone-country');
          const list = document.querySelector('#phone-country-list');
          button.addEventListener('click', () => {
            list.hidden = false;
            button.setAttribute('aria-expanded', 'true');
          });
          document.querySelector('#canada').addEventListener('click', () => {
            button.textContent = '+1';
            button.setAttribute('aria-expanded', 'false');
            list.remove();
          });
        </script>
        """
    )

    outcome = await fill_policy_controls(
        page,
        [_policy("Canada +1", "Country Phone")],
        [],
    )

    assert await page.locator("#phone-country").inner_text() == "+1"
    assert outcome.filled_count == 1
    assert outcome.review_items == []
    assert len(outcome.evidence) == 1
