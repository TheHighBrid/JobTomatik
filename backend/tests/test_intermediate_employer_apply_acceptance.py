from __future__ import annotations

import os

import pytest
import pytest_asyncio

from app.services import application_target_resolver, form_filler_handoff
from app.services.application_target_resolver import resolve_application_target_with_browser
from app.services.employer_application_entry import continue_from_employer_landing
from app.services.form_filler_handoff import fill_and_submit_application_with_handoff


LINKEDIN_URL = "https://www.linkedin.com/jobs/view/9876543210"
DESJARDINS_URL = (
    "https://desjardins-workplace.relevance.studio/en/job-detail/"
    "1-8be45c6a3a60100201e72dd7efbe0001-fraud-prevention-advisor-remote-montreal"
)
WORKDAY_JOB_URL = (
    "https://desjardins.wd10.myworkdayjobs.com/en-US/Desjardins/job/Montral/"
    "Fraud-Prevention-Advisor--Remote_R2511328-1"
)
WORKDAY_APPLY_URL = f"{WORKDAY_JOB_URL}/apply"
WORKDAY_MANUAL_URL = f"{WORKDAY_APPLY_URL}/applyManually"
UNSAFE_URL = "https://careers.example.com/jobs/unsafe-submit"

LINKEDIN_HTML = f"""
<!doctype html>
<html>
  <head><title>Fraud Prevention Advisor | LinkedIn</title></head>
  <body>
    <main>
      <h1>Fraud Prevention Advisor, Remote</h1>
      <a
        id="apply-link"
        href="{DESJARDINS_URL}"
        target="_blank"
        aria-label="Apply on company website"
        data-tracking-control-name="public_jobs_apply-link-offsite_sign-up-modal"
      >Apply ↗</a>
    </main>
  </body>
</html>
"""

# Keep the synthetic click path distinct from the live page's serialized-target
# path. The full Workday URL is deliberately assembled at click time so the generic
# employer doorway must actually click Apply in this acceptance fixture.
DESJARDINS_HTML = """
<!doctype html>
<html>
  <head><title>Fraud Prevention Advisor, Remote | Desjardins</title></head>
  <body>
    <header>Desjardins</header>
    <main>
      <h1>Fraud Prevention Advisor, Remote</h1>
      <div>Full time · Regular position · Montréal · R2511328</div>
      <button id="employer-apply" type="button">Apply</button>
      <script>
        document.querySelector('#employer-apply').addEventListener('click', () => {
          const scheme = 'https:';
          const host = 'desjardins.wd10.' + 'myworkdayjobs.com';
          const path = '/en-US/Desjardins/job/Montral/'
            + 'Fraud-Prevention-Advisor--Remote_' + 'R2511328-1';
          window.location.assign(scheme + '//' + host + path);
        });
      </script>
    </main>
  </body>
</html>
"""

WORKDAY_JOB_HTML = """
<!doctype html>
<html>
  <head><title>Fraud Prevention Advisor, Remote | Desjardins Careers</title></head>
  <body>
    <main>
      <h1>Fraud Prevention Advisor, Remote</h1>
      <div>Job requisition id R2511328</div>
      <button id="workday-apply" type="button"
              data-automation-id="jobPostingApplyButton">Apply</button>
      <script>
        document.querySelector('#workday-apply').addEventListener('click', (event) => {
          event.preventDefault();
        });
      </script>
    </main>
  </body>
</html>
"""

WORKDAY_ADVENTURE_HTML = f"""
<!doctype html>
<html>
  <head><title>Choose how to apply | Desjardins Careers</title></head>
  <body>
    <main data-automation-id="applyAdventurePage">
      <div data-automation-id="legalNotice">Cookie settings</div>
      <button data-automation-id="legalNoticeDeclineButton">Decline</button>
      <a role="button" data-automation-id="autofillWithResume"
         href="{WORKDAY_APPLY_URL}/autofillWithResume">Autofill with Resume</a>
      <a role="button" data-automation-id="applyManually"
         href="{WORKDAY_MANUAL_URL}">Apply Manually</a>
      <a role="button" data-automation-id="useMyLastApplication"
         href="{WORKDAY_APPLY_URL}/useMyLastApplication">Use My Last Application</a>
    </main>
  </body>
</html>
"""

WORKDAY_FORM_HTML = """
<!doctype html>
<html>
  <head><title>Fraud Prevention Advisor | Application</title></head>
  <body>
    <main>
      <h1>Fraud Prevention Advisor, Remote</h1>
      <form id="application_form">
        <label for="first_name">First Name</label>
        <input id="first_name" name="first_name" type="text" required>
        <label for="last_name">Last Name</label>
        <input id="last_name" name="last_name" type="text" required>
        <label for="email">Email</label>
        <input id="email" name="email" type="email" required>
        <label for="phone">Phone</label>
        <input id="phone" name="phone" type="tel" required>
        <label for="resume">Resume</label>
        <input id="resume" name="resume" type="file" accept=".pdf" required>
        <label for="cover_letter">Cover Letter</label>
        <textarea id="cover_letter" name="cover_letter"></textarea>
        <button id="submit_app" type="submit" data-automation-id="submit">Submit Application</button>
      </form>
    </main>
  </body>
</html>
"""

UNSAFE_HTML = """
<!doctype html>
<html>
  <head><title>Unsafe submit fixture</title></head>
  <body>
    <main>
      <h1>Application confirmation</h1>
      <form id="final_form" action="https://careers.example.com/submitted" method="get">
        <button id="dangerous-apply" type="submit">Apply</button>
      </form>
    </main>
  </body>
</html>
"""


class _Runtime:
    def __init__(self, page):
        self.page = page
        self.capture_calls = 0
        self.terminate_calls = 0

    async def capture_snapshot(self, *, metadata=None):
        self.capture_calls += 1
        raise AssertionError("Ordinary Apply navigation must not create a human handoff")

    def terminate(self, *, remove_profile=False):
        self.terminate_calls += 1


@pytest_asyncio.fixture
async def employer_landing_page():
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:
        await playwright.stop()
        if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
            pytest.fail(f"Chromium is required for employer-doorway certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")

    page = await browser.new_page()

    async def route_fixture(route):
        url = route.request.url
        if url.startswith(LINKEDIN_URL):
            await route.fulfill(status=200, content_type="text/html", body=LINKEDIN_HTML)
            return
        if url.startswith(DESJARDINS_URL):
            await route.fulfill(status=200, content_type="text/html", body=DESJARDINS_HTML)
            return
        if url.startswith(WORKDAY_MANUAL_URL):
            await route.fulfill(status=200, content_type="text/html", body=WORKDAY_FORM_HTML)
            return
        if url.startswith(WORKDAY_APPLY_URL):
            await route.fulfill(status=200, content_type="text/html", body=WORKDAY_ADVENTURE_HTML)
            return
        if url.startswith(WORKDAY_JOB_URL):
            await route.fulfill(status=200, content_type="text/html", body=WORKDAY_JOB_HTML)
            return
        if url.startswith(UNSAFE_URL):
            await route.fulfill(status=200, content_type="text/html", body=UNSAFE_HTML)
            return
        if url.startswith("https://careers.example.com/submitted"):
            await route.fulfill(status=200, content_type="text/html", body="submitted")
            return
        await route.abort()

    await page.route("**/*", route_fixture)
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def _profile() -> dict:
    return {
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


async def _assert_filled(page) -> None:
    assert page.url == WORKDAY_MANUAL_URL
    assert await page.locator("#first_name").input_value() == "Test"
    assert await page.locator("#last_name").input_value() == "Candidate"
    assert await page.locator("#email").input_value() == "candidate@example.com"
    assert await page.locator("#phone").input_value() == "613-555-0100"
    uploaded = await page.locator("#resume").evaluate(
        "el => Array.from(el.files || []).map(file => file.name)"
    )
    assert uploaded == ["resume.pdf"]


def _intermediate_actions(result: dict) -> list[dict]:
    return [
        entry
        for entry in result["log"]
        if entry.get("action") == "intermediate_employer_apply_started"
    ]


@pytest.mark.asyncio
async def test_target_resolver_clicks_desjardins_then_yields_to_workday_adapter(
    monkeypatch,
    employer_landing_page,
):
    runtime = _Runtime(employer_landing_page)

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
    assert result["application_target_url"] == WORKDAY_JOB_URL
    assert result["application_form_detected"] is False
    assert result["trusted_ats_adapter"] == "workday"
    assert result["requires_manual_review"] is False
    assert result["handoff_snapshot"] is None
    assert runtime.capture_calls == 0
    assert employer_landing_page.url == WORKDAY_JOB_URL
    intermediate = _intermediate_actions(result)
    assert len(intermediate) == 1
    assert intermediate[0]["url"].startswith(DESJARDINS_URL)
    actions = [entry.get("action") for entry in result["log"]]
    assert "application_entry_external_href_navigated" in actions
    assert "intermediate_employer_trusted_ats_reached" in actions
    assert "workday_application_revealed" not in actions
    assert "application_target_security_handoff_retained" not in actions


@pytest.mark.asyncio
async def test_real_browser_dry_run_lets_workday_own_second_apply_and_fills_form(
    monkeypatch,
    employer_landing_page,
    tmp_path,
):
    runtime = _Runtime(employer_landing_page)

    async def use_test_runtime(_playwright, **_kwargs):
        return runtime

    monkeypatch.setattr(
        form_filler_handoff,
        "launch_application_browser",
        use_test_runtime,
    )

    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n% JobTomatik employer-doorway acceptance fixture\n")

    result = await fill_and_submit_application_with_handoff(
        job_url=LINKEDIN_URL,
        user_profile=_profile(),
        cover_letter="I am interested in the fraud prevention role.",
        resume_path=str(resume),
        dry_run=True,
    )

    assert result["success"] is True
    assert result["ready_to_submit"] is True
    assert result["requires_manual_review"] is False
    assert result["ats_adapter"] == "workday"
    assert result["fields_filled"] >= 5
    assert result["handoff_snapshot"] is None
    assert runtime.capture_calls == 0
    assert len(_intermediate_actions(result)) == 1
    actions = [entry.get("action") for entry in result["log"]]
    assert "intermediate_employer_trusted_ats_reached" in actions
    assert "workday_application_revealed" in actions
    assert "workday_public_apply_route_fallback" in actions
    assert "workday_apply_manually_selected" in actions
    await _assert_filled(employer_landing_page)


@pytest.mark.asyncio
async def test_real_browser_direct_desjardins_dry_run_reaches_workday_owned_form(
    monkeypatch,
    employer_landing_page,
    tmp_path,
):
    runtime = _Runtime(employer_landing_page)

    async def use_test_runtime(_playwright, **_kwargs):
        return runtime

    monkeypatch.setattr(
        form_filler_handoff,
        "launch_application_browser",
        use_test_runtime,
    )

    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n% JobTomatik direct employer acceptance fixture\n")

    result = await fill_and_submit_application_with_handoff(
        job_url=DESJARDINS_URL,
        user_profile=_profile(),
        cover_letter="I am interested in the fraud prevention role.",
        resume_path=str(resume),
        dry_run=True,
    )

    assert result["success"] is True
    assert result["ready_to_submit"] is True
    assert result["requires_manual_review"] is False
    assert result["ats_adapter"] == "workday"
    assert result["fields_filled"] >= 5
    assert result["handoff_snapshot"] is None
    assert runtime.capture_calls == 0
    assert len(_intermediate_actions(result)) == 1
    actions = [entry.get("action") for entry in result["log"]]
    assert "intermediate_employer_trusted_ats_reached" in actions
    assert "workday_application_revealed" in actions
    assert "workday_public_apply_route_fallback" in actions
    assert "workday_apply_manually_selected" in actions
    await _assert_filled(employer_landing_page)


@pytest.mark.asyncio
async def test_intermediate_helper_never_clicks_apply_submit_inside_form(
    employer_landing_page,
):
    await employer_landing_page.goto(UNSAFE_URL, wait_until="domcontentloaded")
    log = []

    result = await continue_from_employer_landing(
        employer_landing_page,
        source_url=LINKEDIN_URL,
        log=log,
        max_steps=1,
        settle_timeout_seconds=0.5,
    )

    assert result == {}
    assert employer_landing_page.url == UNSAFE_URL
    assert any(entry.get("action") == "intermediate_employer_apply_not_found" for entry in log)
