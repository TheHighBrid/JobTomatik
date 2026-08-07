from __future__ import annotations

import os

import pytest
import pytest_asyncio

from app.services import application_target_resolver, form_filler_handoff
from app.services.application_target_resolver import resolve_application_target_with_browser
from app.services.form_filler_handoff import fill_and_submit_application_with_handoff


LINKEDIN_URL = (
    "https://www.linkedin.com/jobs/view/"
    "senior-machine-learning-engineer-fraud-at-affirm-4442675569"
)
GREENHOUSE_URL = "https://job-boards.greenhouse.io/affirm/jobs/7806920003"

LINKEDIN_HTML = f"""
<!doctype html>
<html>
  <head><title>Senior Machine Learning Engineer (Fraud) | LinkedIn</title></head>
  <body>
    <div role="alert">Emails aren't getting through to one of your email addresses. Please update or confirm your email.</div>
    <main>
      <article>
        <div>Affirm</div>
        <h1>Senior Machine Learning Engineer (Fraud)</h1>
        <div>Ottawa, ON · Remote · Full-time</div>
        <a
          id="apply-link"
          href="{GREENHOUSE_URL}"
          target="_blank"
          aria-label="Apply on company website"
          data-tracking-control-name="public_jobs_apply-link-offsite_sign-up-modal"
        >Apply <span aria-hidden="true">↗</span></a>
      </article>
    </main>
  </body>
</html>
"""

GREENHOUSE_HTML = """
<!doctype html>
<html>
  <head><title>Senior Machine Learning Engineer (Fraud) | Affirm</title></head>
  <body>
    <main>
      <h1>Senior Machine Learning Engineer (Fraud)</h1>
      <form id="application_form">
        <div class="field-wrapper">
          <label for="first_name">First Name</label>
          <input id="first_name" name="first_name" type="text" required>
        </div>
        <div class="field-wrapper">
          <label for="last_name">Last Name</label>
          <input id="last_name" name="last_name" type="text" required>
        </div>
        <div class="field-wrapper">
          <label for="email">Email</label>
          <input id="email" name="email" type="email" required>
        </div>
        <div class="field-wrapper">
          <label for="phone">Phone</label>
          <input id="phone" name="phone" type="tel" required>
        </div>
        <div class="field-wrapper">
          <label for="resume">Resume</label>
          <input id="resume" name="resume" type="file" accept=".pdf" required>
        </div>
        <div class="field-wrapper">
          <label for="cover_letter">Cover Letter</label>
          <textarea id="cover_letter" name="cover_letter"></textarea>
        </div>
        <button id="submit_app" type="submit">Submit Application</button>
      </form>
    </main>
  </body>
</html>
"""


class _RetainedTestRuntime:
    def __init__(self, page):
        self.page = page
        self.capture_calls = 0
        self.terminate_calls = 0

    async def capture_snapshot(self, *, metadata=None):
        self.capture_calls += 1
        return {
            "browser_provider": "test",
            "browser_session_id": "unexpected-handoff",
            "current_url": self.page.url,
            "current_fingerprint": "unexpected",
            "metadata": dict(metadata or {}),
        }

    def terminate(self, *, remove_profile=False):
        self.terminate_calls += 1


@pytest_asyncio.fixture
async def routed_browser_page():
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        await playwright.stop()
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required for premature-handoff certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")

    context = await browser.new_context()
    page = await context.new_page()

    async def route_application_fixture(route):
        url = route.request.url
        if url.startswith(LINKEDIN_URL):
            await route.fulfill(status=200, content_type="text/html", body=LINKEDIN_HTML)
            return
        if url.startswith(GREENHOUSE_URL):
            await route.fulfill(status=200, content_type="text/html", body=GREENHOUSE_HTML)
            return
        await route.abort()

    await page.route("**/*", route_application_fixture)
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


@pytest.mark.asyncio
async def test_real_browser_target_resolution_crosses_linkedin_apply_without_handoff(
    monkeypatch,
    routed_browser_page,
):
    runtime = _RetainedTestRuntime(routed_browser_page)

    async def use_test_runtime(_playwright, **_kwargs):
        return runtime

    monkeypatch.setattr(
        application_target_resolver,
        "launch_application_browser",
        use_test_runtime,
    )

    result = await resolve_application_target_with_browser(LINKEDIN_URL)

    assert result["success"] is True
    assert result["application_target_status"] == "resolved"
    assert result["application_target_url"] == GREENHOUSE_URL
    assert result["application_form_detected"] is True
    assert result["requires_manual_review"] is False
    assert result["handoff_snapshot"] is None
    assert runtime.capture_calls == 0
    assert runtime.terminate_calls == 1
    assert routed_browser_page.url == GREENHOUSE_URL
    actions = [entry.get("action") for entry in result["log"]]
    assert "application_entry_external_href_navigated" in actions
    assert "application_entry_resolved" in actions
    assert "application_target_security_handoff_retained" not in actions


@pytest.mark.asyncio
async def test_real_browser_dry_run_fills_greenhouse_after_linkedin_without_handoff(
    monkeypatch,
    routed_browser_page,
    tmp_path,
):
    runtime = _RetainedTestRuntime(routed_browser_page)

    async def use_test_runtime(_playwright, **_kwargs):
        return runtime

    monkeypatch.setattr(
        form_filler_handoff,
        "launch_application_browser",
        use_test_runtime,
    )

    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n% JobTomatik synthetic acceptance fixture\n")
    profile = {
        "full_name": "Test Candidate",
        "email": "candidate@example.com",
        "phone": "613-555-0100",
        "address": "Ottawa, Ontario",
        "linkedin_url": "https://www.linkedin.com/in/test-candidate",
        "github_url": "",
        "portfolio_url": "",
        "profile_data": {},
        "answer_policies": [],
    }

    result = await fill_and_submit_application_with_handoff(
        job_url=LINKEDIN_URL,
        user_profile=profile,
        cover_letter="I am interested in the fraud engineering role.",
        resume_path=str(resume),
        dry_run=True,
    )

    assert result["success"] is True
    assert result["ready_to_submit"] is True
    assert result["requires_manual_review"] is False
    assert result["application_url"] == GREENHOUSE_URL
    assert result["application_form_detected"] is True
    assert result["ats_adapter"] == "greenhouse"
    assert result["fields_filled"] >= 5
    assert result["handoff_snapshot"] is None
    assert runtime.capture_calls == 0
    assert runtime.terminate_calls == 1
    assert await routed_browser_page.locator("#first_name").input_value() == "Test"
    assert await routed_browser_page.locator("#last_name").input_value() == "Candidate"
    assert await routed_browser_page.locator("#email").input_value() == "candidate@example.com"
    assert await routed_browser_page.locator("#phone").input_value() == "613-555-0100"
    assert await routed_browser_page.locator("#cover_letter").input_value() == (
        "I am interested in the fraud engineering role."
    )
    uploaded = await routed_browser_page.locator("#resume").evaluate(
        "el => Array.from(el.files || []).map(file => file.name)"
    )
    assert uploaded == ["resume.pdf"]
    actions = [entry.get("action") for entry in result["log"]]
    assert "browser_handoff_retained" not in actions
    assert "ats_final_submit_ready" in actions
