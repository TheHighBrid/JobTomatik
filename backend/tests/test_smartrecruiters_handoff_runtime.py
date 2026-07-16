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


COMPANY = "smartrecruiters"
POSTING_UUID = "846c9735-28eb-464c-b3aa-4c0407979e0f"


@pytest.mark.asyncio
async def test_smartrecruiters_retained_browser_survives_disconnect_and_resumes_same_form(tmp_path):
    from playwright.async_api import async_playwright

    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nSmartRecruiters resumable handoff certification")

    manager = async_playwright()
    playwright = await manager.start()
    runtime = None
    try:
        try:
            runtime = await launch_retainable_browser(playwright)
        except Exception as exc:
            await playwright.stop()
            if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
                pytest.fail(
                    "Retainable Chromium is required for SmartRecruiters handoff "
                    f"certification: {exc}"
                )
            pytest.skip("Retainable Chromium is not available")

        await runtime.page.set_content(
            f"""
            <form id="smartrecruiters-application" action="https://jobs.smartrecruiters.com/oneclick-ui/company/{COMPANY}/publication/{POSTING_UUID}">
              <label for="first-name">First Name</label>
              <input id="first-name" required>
              <label for="last-name">Last Name</label>
              <input id="last-name" required>
              <label for="email">Email</label>
              <input id="email" type="email" required>
              <label for="resume">Resume</label>
              <input id="resume" type="file" required>
              <iframe id="human-check" src="about:blank?recaptcha"></iframe>
              <textarea name="g-recaptcha-response" hidden></textarea>
              <button id="solve" type="button">Complete human verification</button>
              <button id="submit" type="submit">Submit application</button>
            </form>
            <script>
              document.querySelector('#solve').onclick = () => {{
                document.querySelector('[name="g-recaptcha-response"]').value = 'x'.repeat(64);
                document.querySelector('#human-check').remove();
              }};
              document.querySelector('#smartrecruiters-application').onsubmit = (event) => event.preventDefault();
            </script>
            """
        )
        await runtime.page.locator("#first-name").fill("Avery")
        await runtime.page.locator("#last-name").fill("Certification")
        await runtime.page.locator("#email").fill("avery.certification@example.test")
        await runtime.page.locator("#resume").set_input_files(str(resume))
        button_box = await runtime.page.locator("#solve").bounding_box()
        assert button_box is not None
        snapshot = await runtime.capture_snapshot(
            metadata={"dry_run": True, "adapter": "smartrecruiters"}
        )

        session = ManualHandoffSession(
            public_id="smartrecruiters-browser-runtime-test",
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

        await playwright.stop()

        second_playwright, _, _, retained_page = await _connect_local_cdp(session)
        try:
            assert await retained_page.locator("#first-name").input_value() == "Avery"
            assert await retained_page.locator("#last-name").input_value() == "Certification"
            assert await retained_page.locator("#email").input_value() == (
                "avery.certification@example.test"
            )
            assert await retained_page.locator("#resume").evaluate(
                "(el) => el.files[0].name"
            ) == "resume.pdf"
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
                "full_name": "Avery Certification",
                "first_name": "Avery",
                "last_name": "Certification",
                "email": "avery.certification@example.test",
                "answer_policies": [],
            },
            cover_letter="",
            resume_path=str(resume),
            dry_run=True,
        )
        assert result["success"] is True
        assert result["ready_to_submit"] is True
        assert result["ats_adapter"] == "smartrecruiters"
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
