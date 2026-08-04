import json
import os

import pytest
import pytest_asyncio

from app.services import form_filler_v3
from app.services.text_control_evidence import install_text_control_evidence


install_text_control_evidence()


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
            pytest.fail(f"Chromium is required for text-evidence certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_verified_profile_text_fill_retains_redacted_control_evidence(page):
    synthetic_email = "phase-a-day13@example.invalid"
    await page.set_content(
        """
        <div class="application-field">
          <label for="candidate-email">Email</label>
          <input id="candidate-email" name="email" type="email" required>
        </div>
        """
    )
    log = []

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={
            "email": synthetic_email,
            "answer_policies": [],
        },
        cover_letter="",
        resume_path="",
        log=log,
        step_number=1,
    )

    assert outcome["filled_count"] == 1
    assert outcome["review_items"] == []
    assert len(outcome["control_evidence"]) == 1
    evidence = outcome["control_evidence"][0]
    assert evidence["action"] == "control_verified"
    assert evidence["control_type"] == "text"
    assert evidence["canonical_key"] == "profile.email"
    assert evidence["source"] == "profile"
    assert evidence["verification"] == "passed"
    assert evidence["value_redacted"] is True
    assert synthetic_email not in json.dumps(evidence, sort_keys=True)
    assert await page.locator("#candidate-email").input_value() == synthetic_email


@pytest.mark.asyncio
async def test_text_evidence_installer_is_idempotent(page):
    install_text_control_evidence()
    install_text_control_evidence()
    await page.set_content(
        '<label for="name">Full name</label><input id="name" name="full_name" required>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={
            "full_name": "Synthetic Candidate",
            "answer_policies": [],
        },
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    evidence = [
        item
        for item in outcome["control_evidence"]
        if item.get("canonical_key") == "profile.full_name"
    ]
    assert len(evidence) == 1
