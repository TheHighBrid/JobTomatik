import os

import pytest
import pytest_asyncio

from app.services.control_engine import fill_policy_controls


def policy(answer):
    return {
        "id": 501,
        "canonical_key": "custom.synthetic_location",
        "category": "synthetic_certification",
        "sensitivity": "synthetic",
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "match_phrases": ["Location (City)"],
        "scope": "global",
        "scope_value": "",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-15T00:00:00Z",
    }


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
            pytest.fail(f"Chromium is required for searchable combobox certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_searchable_react_combobox_materializes_and_verifies_suggestion(page):
    await page.set_content(
        """
        <div class="select-container application-field">
          <label id="location-label" for="location">Location (City)*</label>
          <div class="selected-value"></div>
          <input id="location" role="combobox" aria-autocomplete="list"
                 aria-labelledby="location-label" aria-controls="location-list"
                 aria-expanded="false" aria-required="true">
          <input type="hidden" name="location_id" value="">
          <div id="location-list" role="listbox" hidden></div>
        </div>
        <script>
          const input = document.querySelector('#location');
          const list = document.querySelector('#location-list');
          const selected = document.querySelector('.selected-value');
          const hidden = document.querySelector('input[type=hidden]');

          input.addEventListener('click', () => {
            input.setAttribute('aria-expanded', 'true');
          });
          input.addEventListener('input', () => {
            if (input.value.toLowerCase().includes('ottawa')) {
              list.innerHTML = `
                <div role="option" aria-selected="false"
                     data-value="ottawa-on-ca">Ottawa, Ontario, Canada</div>`;
              list.hidden = false;
              input.setAttribute('aria-expanded', 'true');
              const option = list.querySelector('[role=option]');
              option.addEventListener('click', () => {
                option.setAttribute('aria-selected', 'true');
                selected.textContent = option.textContent;
                hidden.value = option.dataset.value;
                input.value = '';
                list.hidden = true;
                input.setAttribute('aria-expanded', 'false');
              });
            }
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
        [policy("Ottawa, Ontario, Canada")],
    )

    assert await page.locator(".selected-value").inner_text() == "Ottawa, Ontario, Canada"
    assert await page.locator('input[type="hidden"]').input_value() == "ottawa-on-ca"
    assert await page.locator("#location").input_value() == ""
    assert await page.locator("#location-list").is_hidden()
    assert outcome.review_items == []
    assert outcome.filled_count == 1
    assert len(outcome.evidence) == 1
