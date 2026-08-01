from __future__ import annotations

import os

import pytest

from scripts.run_lever_phase_a_handoff import (
    SUBMIT_GUARD_SCRIPT,
    SUBMIT_GUARD_STATE_SCRIPT,
)


@pytest.mark.asyncio
async def test_submit_guard_allows_challenge_form_and_blocks_final_application() -> None:
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        await playwright.stop()
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required for the submit-guard contract: {exc}")
        pytest.skip("Chromium is not installed in this environment")

    page = await browser.new_page()
    try:
        await page.set_content(
            """
            <form id="mfa-form">
              <label for="code">Verification code</label>
              <input id="code" name="code" autocomplete="one-time-code">
              <button id="verify-code" type="submit">Verify code</button>
            </form>
            <form id="application-form" class="application-form">
              <label for="resume">Resume</label>
              <input id="resume" type="file">
              <label for="email">Email</label>
              <input id="email" type="email">
              <button id="submit-application" type="submit">Submit application</button>
            </form>
            """
        )
        await page.evaluate(SUBMIT_GUARD_SCRIPT)
        outcomes = await page.evaluate(
            """
            () => {
              const mfa = document.querySelector('#mfa-form');
              const application = document.querySelector('#application-form');
              const mfaSubmitter = document.querySelector('#verify-code');
              const applicationSubmitter = document.querySelector('#submit-application');
              const mfaAllowed = mfa.dispatchEvent(new SubmitEvent('submit', {
                bubbles: true,
                cancelable: true,
                submitter: mfaSubmitter,
              }));
              const applicationAllowed = application.dispatchEvent(new SubmitEvent('submit', {
                bubbles: true,
                cancelable: true,
                submitter: applicationSubmitter,
              }));
              return { mfaAllowed, applicationAllowed };
            }
            """
        )
        state = await page.evaluate(SUBMIT_GUARD_STATE_SCRIPT)
    finally:
        await browser.close()
        await playwright.stop()

    assert outcomes == {
        "mfaAllowed": True,
        "applicationAllowed": False,
    }
    assert state == {
        "installed": True,
        "blocked_clicks": 0,
        "blocked_submits": 1,
    }
