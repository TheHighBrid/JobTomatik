import os

import pytest
import pytest_asyncio

# Install the Lever Phase A compatibility layer before importing the synthetic
# answer helper that the certification profile uses.
from app.services import form_filler as _form_filler  # noqa: F401
from app.services.lever_certification import (
    SYNTHETIC_LOCATION,
    build_synthetic_profile,
    choose_synthetic_answer,
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


def test_canada_location_question_matches_yes() -> None:
    answer = choose_synthetic_answer(
        "Are you located in Canada?",
        ["Yes", "No"],
        control_type="radio",
    )
    assert answer == "Yes"


def test_canada_work_eligibility_question_matches_yes() -> None:
    answer = choose_synthetic_answer(
        "Are you legally eligible to work in Canada with no restrictions?",
        ["Yes (PR, open work permit, etc.)", "No"],
        control_type="radio",
    )
    assert answer == "Yes (PR, open work permit, etc.)"


def test_salary_alignment_question_matches_yes() -> None:
    answer = choose_synthetic_answer(
        "Have you reviewed the posted salary range and are your expectations aligned with it?",
        ["Yes", "No"],
        control_type="radio",
    )
    assert answer == "Yes"


def test_desired_salary_uses_numeric_synthetic_value() -> None:
    answer = choose_synthetic_answer(
        "What is your desired salary? Please write down a number.",
        [],
        control_type="text",
    )
    assert answer == "150000"
