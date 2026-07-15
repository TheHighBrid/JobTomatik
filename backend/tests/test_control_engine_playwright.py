import os

import pytest
import pytest_asyncio

from app.services.control_engine import CONTROL_ENGINE_VERSION, fill_policy_controls


def policy(
    canonical_key,
    answer,
    *,
    category="custom",
    sensitivity="standard",
    phrases=None,
    policy_id=1,
):
    return {
        "id": policy_id,
        "canonical_key": canonical_key,
        "category": category,
        "sensitivity": sensitivity,
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "match_phrases": phrases or [],
        "scope": "global",
        "scope_value": "",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-15T10:00:00",
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
            pytest.fail(f"Chromium is required for control certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")

    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_native_select_radio_and_checkbox_matrix(page):
    await page.set_content(
        """
        <form>
          <label for="auth">Are you legally authorized to work in Canada?</label>
          <select id="auth" required>
            <option value="">Select</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>

          <fieldset>
            <legend>Will you now or in the future require sponsorship?</legend>
            <label><input type="radio" name="sponsor" value="yes" required>Yes</label>
            <label><input type="radio" name="sponsor" value="no">No</label>
          </fieldset>

          <label>
            <input id="certify" type="checkbox" required>
            I certify that the information in this application is accurate
          </label>

          <fieldset>
            <legend>Which work arrangements would you accept?</legend>
            <label><input type="checkbox" name="arrangement" value="remote" required>Remote</label>
            <label><input type="checkbox" name="arrangement" value="hybrid">Hybrid</label>
            <label><input type="checkbox" name="arrangement" value="onsite">On-site</label>
          </fieldset>
        </form>
        """
    )
    policies = [
        policy("work_authorization", "Yes", category="work_authorization", sensitivity="legal", policy_id=1),
        policy("sponsorship_required", "No", category="sponsorship", sensitivity="legal", policy_id=2),
        policy("terms_consent", "Yes", category="consent", sensitivity="legal", policy_id=3),
        policy(
            "custom.work_arrangements",
            '["Remote", "Hybrid"]',
            phrases=["which work arrangements"],
            policy_id=4,
        ),
    ]

    outcome = await fill_policy_controls(page, policies)

    assert await page.locator("#auth").input_value() == "yes"
    assert await page.locator('input[name="sponsor"][value="no"]').is_checked()
    assert await page.locator("#certify").is_checked()
    assert await page.locator('input[name="arrangement"][value="remote"]').is_checked()
    assert await page.locator('input[name="arrangement"][value="hybrid"]').is_checked()
    assert not await page.locator('input[name="arrangement"][value="onsite"]').is_checked()
    assert outcome.review_items == []
    assert outcome.filled_count == 4
    assert len(outcome.evidence) == 4
    assert {item["control_engine_version"] for item in outcome.evidence} == {CONTROL_ENGINE_VERSION}


@pytest.mark.asyncio
async def test_multiselect_datalist_ungrouped_radio_and_conditional_rescan(page):
    await page.set_content(
        """
        <form>
          <label for="locations">Preferred office locations</label>
          <select id="locations" multiple required>
            <option value="ottawa">Ottawa</option>
            <option value="montreal">Montreal</option>
            <option value="toronto">Toronto</option>
          </select>

          <label for="start">Availability or start date</label>
          <input id="start" list="start-options" required>
          <datalist id="start-options">
            <option value="Immediately"></option>
            <option value="Two weeks"></option>
          </datalist>

          <label><input type="radio" name="relocate" value="yes" required>Yes, willing to relocate</label>
          <label><input type="radio" name="relocate" value="no">No, not willing to relocate</label>

          <div id="conditional"></div>
          <script>
            document.querySelectorAll('input[name="relocate"]').forEach((radio) => {
              radio.addEventListener('change', () => {
                if (radio.value === 'yes' && radio.checked) {
                  document.querySelector('#conditional').innerHTML = `
                    <label for="region">Preferred relocation region</label>
                    <select id="region" required>
                      <option value="">Choose one</option>
                      <option value="quebec">Quebec</option>
                      <option value="ontario">Ontario</option>
                    </select>`;
                }
              });
            });
          </script>
        </form>
        """
    )
    policies = [
        policy(
            "custom.preferred_locations",
            '["Ottawa", "Montreal"]',
            phrases=["preferred office locations"],
            policy_id=10,
        ),
        policy("availability_date", "Two weeks", category="availability", policy_id=11),
        policy("willing_to_relocate", "Yes", category="relocation", policy_id=12),
        policy(
            "custom.relocation_region",
            "Quebec",
            phrases=["preferred relocation region"],
            policy_id=13,
        ),
    ]

    outcome = await fill_policy_controls(page, policies)

    selected_locations = await page.locator("#locations").evaluate(
        "(el) => Array.from(el.selectedOptions).map((option) => option.value)"
    )
    assert selected_locations == ["ottawa", "montreal"]
    assert await page.locator("#start").input_value() == "Two weeks"
    assert await page.locator('input[name="relocate"][value="yes"]').is_checked()
    assert await page.locator("#region").input_value() == "quebec"
    assert outcome.review_items == []
    assert outcome.filled_count == 4
    assert outcome.passes >= 2


@pytest.mark.asyncio
async def test_aria_combobox_radio_and_checkbox_matrix(page):
    await page.set_content(
        """
        <form>
          <label id="source-label">How did you hear about this role?</label>
          <button id="source" type="button" role="combobox"
                  aria-labelledby="source-label" aria-controls="source-list"
                  aria-expanded="false">Choose source</button>
          <div id="source-list" role="listbox" hidden>
            <div role="option" data-value="linkedin" aria-selected="false">LinkedIn</div>
            <div role="option" data-value="referral" aria-selected="false">Employee referral</div>
          </div>

          <div role="radiogroup" aria-label="Are you currently employed?" aria-required="true">
            <button type="button" role="radio" aria-checked="false" data-value="yes">Yes</button>
            <button type="button" role="radio" aria-checked="false" data-value="no">No</button>
          </div>

          <button id="privacy" type="button" role="checkbox" aria-checked="false"
                  aria-label="I consent to processing my applicant data"
                  aria-required="true">Privacy consent</button>

          <script>
            const combo = document.querySelector('#source');
            const list = document.querySelector('#source-list');
            combo.addEventListener('click', () => {
              list.hidden = false;
              combo.setAttribute('aria-expanded', 'true');
            });
            list.querySelectorAll('[role="option"]').forEach((option) => {
              option.addEventListener('click', () => {
                list.querySelectorAll('[role="option"]').forEach((item) => item.setAttribute('aria-selected', 'false'));
                option.setAttribute('aria-selected', 'true');
                combo.textContent = option.textContent;
                combo.setAttribute('aria-expanded', 'false');
                list.hidden = true;
              });
            });
            document.querySelectorAll('[role="radio"]').forEach((radio) => {
              radio.addEventListener('click', () => {
                radio.parentElement.querySelectorAll('[role="radio"]').forEach((item) => item.setAttribute('aria-checked', 'false'));
                radio.setAttribute('aria-checked', 'true');
              });
            });
            document.querySelector('#privacy').addEventListener('click', (event) => {
              const current = event.currentTarget.getAttribute('aria-checked') === 'true';
              event.currentTarget.setAttribute('aria-checked', String(!current));
            });
          </script>
        </form>
        """
    )
    policies = [
        policy("referral_source", "LinkedIn", category="source", policy_id=20),
        policy("currently_employed", "No", category="employment", policy_id=21),
        policy("data_processing_consent", "Yes", category="consent", sensitivity="legal", policy_id=22),
    ]

    outcome = await fill_policy_controls(page, policies)

    assert await page.locator("#source").inner_text() == "LinkedIn"
    assert await page.locator('[role="radio"][data-value="no"]').get_attribute("aria-checked") == "true"
    assert await page.locator("#privacy").get_attribute("aria-checked") == "true"
    assert outcome.review_items == []
    assert outcome.filled_count == 3


@pytest.mark.asyncio
async def test_missing_optional_and_ambiguous_controls_are_never_guessed(page):
    await page.set_content(
        """
        <form>
          <label for="required-auth">Are you legally authorized to work?</label>
          <select id="required-auth" required>
            <option value="">Select</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>

          <label for="optional-source">How did you hear about us?</label>
          <select id="optional-source">
            <option value="">Select</option>
            <option value="linkedin">LinkedIn</option>
            <option value="other">Other</option>
          </select>

          <label for="ambiguous">Are you eligible to work?</label>
          <select id="ambiguous" required>
            <option value="">Choose</option>
            <option value="citizen">Yes - citizen</option>
            <option value="resident">Yes - permanent resident</option>
          </select>

          <label>
            <input id="decline-required" type="checkbox" required>
            I agree to the application terms
          </label>
        </form>
        """
    )
    policies = [
        policy("work_authorization", "Yes", category="work_authorization", sensitivity="legal", policy_id=30),
        policy("terms_consent", "No", category="consent", sensitivity="legal", policy_id=31),
    ]

    outcome = await fill_policy_controls(page, policies)

    assert await page.locator("#required-auth").input_value() == "yes"
    assert await page.locator("#optional-source").input_value() == ""
    assert await page.locator("#ambiguous").input_value() == ""
    assert not await page.locator("#decline-required").is_checked()

    summaries = " ".join(item["summary"] for item in outcome.review_items)
    assert "unambiguously" in summaries
    assert "does not satisfy this required checkbox" in summaries
    assert len(outcome.review_items) == 2
