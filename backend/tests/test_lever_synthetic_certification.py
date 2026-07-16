import os

import pytest
import pytest_asyncio

from app.services.lever_certification import (
    SYNTHETIC_LOCATION,
    build_synthetic_profile,
    inspect_lever_application_dom,
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
            pytest.fail(f"Chromium is required for Lever certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_lever_dom_inventory_builds_only_required_synthetic_policies(page):
    await page.set_content(
        """
        <form class="application-form">
          <label for="resume">Resume/CV</label>
          <input id="resume" type="file" required>
          <label for="name">Full name</label>
          <input id="name" required>
          <label for="email">Email</label>
          <input id="email" required>
          <label for="location">Current location</label>
          <input id="location" role="combobox" aria-required="true">
          <label for="auth">Are you legally authorized to work in Canada?</label>
          <select id="auth" required>
            <option value="">Select</option><option>Yes</option><option>No</option>
          </select>
          <label><input id="terms" type="checkbox" required>I certify this application is accurate</label>
          <fieldset>
            <legend>Gender Identity</legend>
            <label><input type="radio" name="gender" value="prefer">Prefer not to disclose</label>
          </fieldset>
          <button type="submit">Submit application</button>
        </form>
        """
    )

    inventory = await inspect_lever_application_dom(page)
    profile = build_synthetic_profile(inventory)
    phrases = [
        policy["match_phrases"][0].lower()
        for policy in profile["answer_policies"]
    ]

    assert inventory["visible_control_count"] >= 7
    assert inventory["required_control_count"] >= 6
    assert any("current location" in phrase for phrase in phrases)
    assert any("authorized to work" in phrase for phrase in phrases)
    assert any("certify" in phrase or "accurate" in phrase for phrase in phrases)
    assert not any("gender identity" in phrase for phrase in phrases)

    location_policy = next(
        policy for policy in profile["answer_policies"]
        if "current location" in policy["match_phrases"][0].lower()
    )
    assert location_policy["answer_value"] == SYNTHETIC_LOCATION
    assert all(policy["allow_autofill"] is True for policy in profile["answer_policies"])
    assert profile["synthetic_certification_only"] is True
