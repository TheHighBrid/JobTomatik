import os

import pytest

from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.services.browser_handoff import (
    _connect_local_cdp,
    _disconnect,
    perform_handoff_action,
    resume_handoff_application,
    verify_browser_handoff_completion,
)
from app.services.browser_runtime import launch_retainable_browser
from app.services.handoff_session import encrypt_handoff_secret


@pytest.mark.asyncio
async def test_retained_browser_survives_disconnect_and_resumes_same_form(tmp_path):
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    runtime = None
    try:
        try:
            runtime = await launch_retainable_browser(playwright)
        except Exception as exc:
            await playwright.stop()
            if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
                pytest.fail(f"Retainable Chromium is required for handoff certification: {exc}")
            pytest.skip("Retainable Chromium is not available")

        await runtime.page.set_content(
            """
            <form id="application_form">
              <label for="first_name">First Name</label>
              <input id="first_name" name="first_name" required>
              <iframe id="human-check" src="https://www.google.com/recaptcha/api2/anchor"></iframe>
              <textarea name="g-recaptcha-response" hidden></textarea>
              <button id="solve" type="button">Complete human verification</button>
              <button id="submit_app" type="submit">Submit Application</button>
            </form>
            <script>
              document.querySelector('#solve').onclick = () => {
                document.querySelector('[name="g-recaptcha-response"]').value = 'x'.repeat(64);
                document.querySelector('#human-check').remove();
              };
              document.querySelector('#application_form').onsubmit = (event) => event.preventDefault();
            </script>
            """
        )
        await runtime.page.locator("#first_name").fill("Avery")
        button_box = await runtime.page.locator("#solve").bounding_box()
        assert button_box is not None
        snapshot = await runtime.capture_snapshot(metadata={"dry_run": True})

        session = ManualHandoffSession(
            public_id="browser-runtime-test",
            application_id=1,
            manual_review_id=1,
            user_id=1,
            challenge_type=HandoffChallengeType.captcha.value,
            browser_provider=snapshot["browser_provider"],
            browser_session_id=snapshot["browser_session_id"],
            encrypted_browser_endpoint=encrypt_handoff_secret(snapshot["browser_endpoint"]),
            browser_node_id=snapshot["browser_node_id"],
            browser_process_id=snapshot["browser_process_id"],
            browser_profile_path=snapshot["browser_profile_path"],
            current_url=snapshot["current_url"],
            current_fingerprint=snapshot["current_fingerprint"],
        )

        # Disconnect the original controller. The separately launched Chromium
        # process must retain its profile, DOM, cookies, focus, and field values.
        await playwright.stop()

        second_playwright, _, _, retained_page = await _connect_local_cdp(session)
        try:
            assert await retained_page.locator("#first_name").input_value() == "Avery"
            assert await retained_page.locator("#human-check").count() == 1
        finally:
            await _disconnect(second_playwright)

        before = await verify_browser_handoff_completion(session)
        assert before.challenge_cleared is False

        await perform_handoff_action(
            session,
            action="click",
            x=button_box["x"] + button_box["width"] / 2,
            y=button_box["y"] + button_box["height"] / 2,
        )
        after = await verify_browser_handoff_completion(session)
        assert after.challenge_cleared is True
        assert after.evidence["has_completed_response"] is True

        result = await resume_handoff_application(
            session,
            user_profile={
                "first_name": "Avery",
                "full_name": "Avery Certification",
                "answer_policies": [],
            },
            cover_letter="",
            resume_path="",
            dry_run=True,
        )
        assert result["success"] is True
        assert result["ready_to_submit"] is True
        assert result["ats_adapter"] == "greenhouse"
        assert not any(
            item.get("action") == "ats_submit_clicked"
            for item in result.get("log") or []
        )
    finally:
        if runtime is not None:
            runtime.terminate(remove_profile=True)
        try:
            await playwright.stop()
        except Exception:
            pass
