import os

import pytest
import pytest_asyncio

from app.services.control_engine import fill_policy_controls


def policy(key, answer, phrase, policy_id):
    return {
        "id": policy_id,
        "canonical_key": key,
        "category": "synthetic_certification",
        "sensitivity": "synthetic",
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "match_phrases": [phrase],
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
            pytest.fail(f"Chromium is required for combobox overlay certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_open_combobox_overlay_is_closed_before_next_control(page):
    await page.set_content(
        """
        <style>
          .combo-wrap { position: relative; margin: 10px; }
          [role=listbox] {
            position: absolute;
            z-index: 20;
            width: 260px;
            min-height: 90px;
            background: white;
            border: 1px solid black;
          }
          #country-list { top: 30px; left: 0; }
          #source-wrap { margin-top: 40px; }
        </style>

        <div class="combo-wrap">
          <label id="country-label">Current country of residence</label>
          <button id="country" type="button" role="combobox"
                  aria-labelledby="country-label" aria-controls="country-list"
                  aria-expanded="false" aria-required="true">Choose country</button>
          <div id="country-list" role="listbox" hidden>
            <div role="option" aria-selected="false" data-value="canada">Canada</div>
            <div role="option" aria-selected="false" data-value="bulgaria">Bulgaria</div>
          </div>
        </div>

        <div id="source-wrap" class="combo-wrap">
          <label id="source-label">How did you hear about this role?</label>
          <button id="source" type="button" role="combobox"
                  aria-labelledby="source-label" aria-controls="source-list"
                  aria-expanded="false" aria-required="true">Choose source</button>
          <div id="source-list" role="listbox" hidden>
            <div role="option" aria-selected="false" data-value="linkedin">LinkedIn</div>
            <div role="option" aria-selected="false" data-value="other">Other</div>
          </div>
        </div>

        <script>
          function openCombo(buttonId, listId) {
            const button = document.querySelector(buttonId);
            const list = document.querySelector(listId);
            button.addEventListener('click', () => {
              list.hidden = false;
              button.setAttribute('aria-expanded', 'true');
            });
            return {button, list};
          }

          const country = openCombo('#country', '#country-list');
          country.list.querySelectorAll('[role=option]').forEach((option) => {
            option.addEventListener('click', () => {
              country.list.querySelectorAll('[role=option]').forEach(
                (item) => item.setAttribute('aria-selected', 'false')
              );
              option.setAttribute('aria-selected', 'true');
              country.button.textContent = option.textContent;
              // Intentionally remain open to reproduce the live Greenhouse overlay defect.
            });
          });

          const source = openCombo('#source', '#source-list');
          source.list.querySelectorAll('[role=option]').forEach((option) => {
            option.addEventListener('click', () => {
              source.list.querySelectorAll('[role=option]').forEach(
                (item) => item.setAttribute('aria-selected', 'false')
              );
              option.setAttribute('aria-selected', 'true');
              source.button.textContent = option.textContent;
              source.list.hidden = true;
              source.button.setAttribute('aria-expanded', 'false');
            });
          });

          document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
              document.querySelectorAll('[role=listbox]').forEach((list) => {
                list.hidden = true;
              });
              document.querySelectorAll('[role=combobox]').forEach((button) => {
                button.setAttribute('aria-expanded', 'false');
              });
            }
          });
        </script>
        """
    )

    outcome = await fill_policy_controls(page, [
        policy(
            "custom.synthetic_country",
            "Canada",
            "current country of residence",
            1,
        ),
        policy(
            "custom.synthetic_source",
            "LinkedIn",
            "how did you hear about this role",
            2,
        ),
    ])

    assert await page.locator("#country").inner_text() == "Canada"
    assert await page.locator("#source").inner_text() == "LinkedIn"
    assert await page.locator("#country-list").is_hidden()
    assert await page.locator("#source-list").is_hidden()
    assert outcome.review_items == []
    assert outcome.filled_count == 2
    assert len(outcome.evidence) == 2
