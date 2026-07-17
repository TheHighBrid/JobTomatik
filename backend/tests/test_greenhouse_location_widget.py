import os

import pytest
import pytest_asyncio

# Importing the public form-filler entrypoint installs Greenhouse compatibility.
from app.services import form_filler as _form_filler  # noqa: F401
from app.services.control_engine import fill_policy_controls
from app.services.greenhouse_location_widget import wait_for_location_options


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
            pytest.fail(f"Chromium is required for Greenhouse location tests: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def _policy(answer: str):
    return {
        "id": 1,
        "canonical_key": "custom.synthetic_location",
        "category": "synthetic_certification",
        "sensitivity": "synthetic",
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "match_phrases": ["Location (City)"],
        "scope": "platform",
        "scope_value": "greenhouse",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-15T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_delayed_location_option_is_selected_only_after_real_option_appears(page):
    await page.set_content(
        """
        <div class="application-field">
          <label id="location-label" for="candidate-location">Location (City)*</label>
          <input id="candidate-location" name="candidate-location"
                 role="combobox" aria-autocomplete="list"
                 aria-labelledby="location-label"
                 aria-controls="location-list"
                 aria-expanded="false" aria-required="true">
          <div id="location-list" role="listbox" hidden></div>
        </div>
        <script>
          const input = document.querySelector('#candidate-location');
          const list = document.querySelector('#location-list');
          let timer;
          input.addEventListener('input', () => {
            clearTimeout(timer);
            list.hidden = true;
            list.innerHTML = '';
            if (!input.value.toLowerCase().includes('ottawa')) return;
            timer = setTimeout(() => {
              const option = document.createElement('div');
              option.id = 'ottawa-option';
              option.setAttribute('role', 'option');
              option.setAttribute('aria-selected', 'false');
              option.textContent = 'Ottawa, Ontario, Canada';
              option.addEventListener('click', () => {
                input.value = option.textContent;
                input.setAttribute('aria-expanded', 'false');
                list.hidden = true;
              });
              list.appendChild(option);
              list.hidden = false;
              input.setAttribute('aria-expanded', 'true');
            }, 900);
          });
          document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
              list.hidden = true;
              input.setAttribute('aria-expanded', 'false');
            }
          });
        </script>
        """
    )

    outcome = await fill_policy_controls(
        page,
        [_policy("Ottawa, Ontario, Canada")],
        [],
    )

    assert await page.locator("#candidate-location").input_value() == (
        "Ottawa, Ontario, Canada"
    )
    assert outcome.filled_count == 1
    assert outcome.review_items == []
    assert len(outcome.evidence) == 1


@pytest.mark.asyncio
async def test_location_retry_fails_closed_when_no_real_option_appears(page):
    await page.set_content(
        """
        <label id="location-label" for="candidate-location">Location (City)*</label>
        <input id="candidate-location" role="combobox"
               aria-autocomplete="list" aria-labelledby="location-label"
               aria-controls="location-list" aria-required="true">
        <div id="location-list" role="listbox" hidden></div>
        """
    )
    combobox = await page.query_selector("#candidate-location")

    ready = await wait_for_location_options(
        page,
        combobox,
        "Ottawa, Ontario, Canada",
        attempts=2,
        delay_ms=25,
    )

    assert ready is False
    assert await page.locator("#candidate-location").input_value() == (
        "Ottawa, Ontario, Canada"
    )
    assert await page.locator("#location-list [role=option]").count() == 0
