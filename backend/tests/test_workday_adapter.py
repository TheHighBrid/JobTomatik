import os

import pytest
import pytest_asyncio

from app.services.ats_flow import run_ats_application_flow
from app.services.ats_registry import detect_ats_adapter
from app.services.ats_workday import (
    WorkdayAdapter,
    WorkdayTarget,
    inspect_workday_job_metadata,
    parse_workday_target,
    workday_cxs_job_url,
)
from app.services.form_filler_v3 import _fill_step_fields
from app.services.workday_challenge import detect_workday_login_or_account_boundary


WORKDAY_URL = (
    "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/"
    "Ottawa/Information-Security-Analyst_R-123?source=private#tracking"
)
SAFE_WORKDAY_URL = (
    "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/"
    "Ottawa/Information-Security-Analyst_R-123"
)


def policy(
    key,
    answer,
    *,
    phrases=None,
    category="custom",
    sensitivity="standard",
    policy_id=1,
):
    return {
        "id": policy_id,
        "canonical_key": key,
        "category": category,
        "sensitivity": sensitivity,
        "mode": "answer",
        "answer_value": answer,
        "answer_label": answer,
        "match_phrases": phrases or [],
        "scope": "platform",
        "scope_value": "myworkdayjobs.com",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-16T10:00:00",
    }


@pytest_asyncio.fixture
async def browser_page():
    from playwright.async_api import async_playwright

    manager = async_playwright()
    playwright = await manager.start()
    browser = None
    context = None
    try:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as exc:
            if os.getenv("REQUIRE_BROWSER_TESTS") == "1":
                pytest.fail(f"Chromium is required for Workday certification: {exc}")
            pytest.skip("Chromium is not installed in this environment")
        context = await browser.new_context()
        page = await context.new_page()
        yield page
    finally:
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()
        await playwright.stop()


def test_workday_target_parser_is_strict_and_query_free():
    target = parse_workday_target(WORKDAY_URL)
    assert target == WorkdayTarget(
        host="acme.wd5.myworkdayjobs.com",
        tenant="acme",
        cluster="wd5",
        site="Careers",
        job_id="R-123",
        safe_url=SAFE_WORKDAY_URL,
    )
    assert workday_cxs_job_url(target) == (
        "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/job/R-123"
    )
    assert "?" not in target.safe_url
    assert "#" not in target.safe_url

    assert parse_workday_target("https://acme.wd5.myworkdayjobs.com/en-US/Careers") is None
    assert parse_workday_target(
        "https://acme.wd5.myworkdayjobs.com/en-US/Careers/candidate-home"
    ) is None
    assert parse_workday_target("https://example.com/Careers/job/Ottawa/R-123") is None
    assert parse_workday_target("https://wd5.myworkdayjobs.com/") is None


def test_workday_public_cxs_metadata_contract():
    target = parse_workday_target(WORKDAY_URL)
    assert target is not None
    report = inspect_workday_job_metadata(
        {
            "jobPostingInfo": {
                "title": "Information Security Analyst",
                "jobDescription": "A current fictional certification role.",
                "jobRequisitionId": "R-123",
                "externalUrl": (
                    "/en-US/Careers/job/Ottawa/"
                    "Information-Security-Analyst_R-123"
                ),
                "location": "Ottawa, Ontario",
                "timeType": "Full time",
                "workerType": "Regular",
                "remoteType": "Hybrid",
            }
        },
        target,
    )
    assert report["public_metadata_certified"] is True
    assert report["requisition_matches_target"] is True
    assert report["external_path_matches_target"] is True
    assert report["description_present"] is True

    mismatch = inspect_workday_job_metadata(
        {"jobPostingInfo": {"title": "Other role", "jobRequisitionId": "R-999"}},
        target,
    )
    assert mismatch["public_metadata_certified"] is False


@pytest.mark.asyncio
async def test_registry_detects_workday_without_generic_false_positive(browser_page):
    await browser_page.set_content(
        f'<form action="{SAFE_WORKDAY_URL}">'
        '<button data-automation-id="bottom-navigation-next-button">Next</button>'
        "</form>"
    )
    adapter = await detect_ats_adapter(browser_page, SAFE_WORKDAY_URL)
    assert adapter.name == "workday"
    assert adapter.certification_level == "fixture_pending_live_certification"

    other = await browser_page.context.new_page()
    try:
        await other.set_content('<form class="application-form"></form>')
        generic = await detect_ats_adapter(other, "https://careers.example.test/job")
        assert generic.name == "generic"
    finally:
        await other.close()


@pytest.mark.asyncio
async def test_workday_bounded_apply_transition(browser_page):
    await browser_page.set_content(
        """
        <main>
          <button id="apply" data-automation-id="jobPostingApplyButton">Apply Now</button>
          <form id="application" hidden>
            <label for="email">Email</label><input id="email" type="email" required>
            <button data-automation-id="bottom-navigation-next-button">Next</button>
          </form>
        </main>
        <script>
          window.applyClicks = 0;
          document.querySelector('#apply').onclick = () => {
            window.applyClicks += 1;
            document.querySelector('#apply').hidden = true;
            document.querySelector('#application').hidden = false;
          };
        </script>
        """
    )
    log = []
    await WorkdayAdapter().prepare(browser_page, log)
    assert await browser_page.evaluate("window.applyClicks") == 1
    assert await browser_page.locator("#application").is_visible()
    assert log[-1]["bounded_apply_transition"] is True


@pytest.mark.asyncio
async def test_workday_multistep_dynamic_combobox_upload_and_dry_run(browser_page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nJobTomatik Workday donor-port certification")

    await browser_page.set_content(
        f"""
        <form id="workday-application" action="{SAFE_WORKDAY_URL}">
          <section id="step-1">
            <label for="first">First Name</label><input id="first" required>
            <label for="last">Last Name</label><input id="last" required>
            <label for="email">Email</label><input id="email" type="email" required>
            <div class="application-field" data-field>
              <label for="location">Current Location</label>
              <input id="location" role="combobox" aria-label="Current Location"
                     aria-required="true" aria-controls="locations"
                     aria-autocomplete="list" aria-expanded="false">
              <input id="location-hidden" type="hidden">
              <div id="locations" role="listbox" hidden>
                <div role="option" data-value="Ottawa, Ontario">Ottawa, Ontario</div>
                <div role="option" data-value="Toronto, Ontario">Toronto, Ontario</div>
              </div>
            </div>
            <button id="next-1" type="button"
                    data-automation-id="bottom-navigation-next-button">Next</button>
          </section>
          <section id="step-2" hidden>
            <label for="auth">Are you legally authorized to work in Canada?</label>
            <select id="auth" required>
              <option value="">Select one</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
            <label for="interest">Why are you interested in this role?</label>
            <textarea id="interest" required></textarea>
            <div id="conditional"></div>
            <label for="resume">Resume</label>
            <input id="resume" type="file" accept=".pdf" required>
            <button id="next-2" type="button"
                    data-automation-id="bottom-navigation-next-button">Next</button>
          </section>
          <section id="step-3" hidden>
            <label>
              <input id="privacy" type="checkbox" required>
              I consent to processing my applicant data
            </label>
            <button id="submit" type="submit"
                    data-automation-id="bottom-navigation-submit-button">
              Submit Application
            </button>
          </section>
        </form>
        <script>
          const combo = document.querySelector('#location');
          const listbox = document.querySelector('#locations');
          combo.onclick = () => {
            listbox.hidden = false;
            combo.setAttribute('aria-expanded', 'true');
          };
          document.querySelectorAll('#locations [role=option]').forEach((option) => {
            option.onclick = () => {
              combo.value = option.textContent.trim();
              document.querySelector('#location-hidden').value = option.dataset.value;
              combo.setAttribute('aria-expanded', 'false');
              listbox.hidden = true;
            };
          });
          document.querySelector('#next-1').onclick = () => {
            document.querySelector('#step-1').hidden = true;
            document.querySelector('#step-2').hidden = false;
          };
          document.querySelector('#auth').onchange = (event) => {
            if (event.target.value === 'yes') {
              document.querySelector('#conditional').innerHTML =
                '<label for="start">Available start date</label>' +
                '<input id="start" type="date" required>';
            }
          };
          document.querySelector('#next-2').onclick = () => {
            document.querySelector('#step-2').hidden = true;
            document.querySelector('#step-3').hidden = false;
          };
          document.querySelector('#workday-application').onsubmit = (event) => {
            event.preventDefault();
            window.submitAttempts = (window.submitAttempts || 0) + 1;
          };
        </script>
        """
    )

    profile = {
        "full_name": "Avery Certification",
        "first_name": "Avery",
        "last_name": "Certification",
        "email": "avery.certification@example.test",
        "answer_policies": [
            policy(
                "custom.workday_current_location",
                "Ottawa, Ontario",
                phrases=["current location"],
                policy_id=1,
            ),
            policy(
                "work_authorization",
                "Yes",
                category="work_authorization",
                sensitivity="legal",
                policy_id=2,
            ),
            policy(
                "custom.workday_interest",
                "Synthetic Workday certification response. This form will not be submitted.",
                phrases=["why are you interested in this role"],
                policy_id=3,
            ),
            policy(
                "custom.available_start_date",
                "2026-08-15",
                phrases=["available start date"],
                policy_id=4,
            ),
            policy(
                "data_processing_consent",
                "Yes",
                category="consent",
                sensitivity="legal",
                policy_id=5,
            ),
        ],
    }
    log = []

    async def fill_step(surface, step_number):
        return await _fill_step_fields(
            surface,
            profile=profile,
            cover_letter="",
            resume_path=str(resume),
            log=log,
            step_number=step_number,
        )

    result = await run_ats_application_flow(
        browser_page,
        WorkdayAdapter(),
        fill_step=fill_step,
        dry_run=True,
        log=log,
    )

    assert result.success is True
    assert result.ready_to_submit is True
    assert result.requires_manual_review is False
    assert result.steps_completed == 3
    assert await browser_page.locator("#first").input_value() == "Avery"
    assert await browser_page.locator("#last").input_value() == "Certification"
    assert await browser_page.locator("#location").input_value() == "Ottawa, Ontario"
    assert await browser_page.locator("#location-hidden").input_value() == "Ottawa, Ontario"
    assert await browser_page.locator("#start").input_value() == "2026-08-15"
    assert await browser_page.locator("#resume").evaluate("(el) => el.files[0].name") == "resume.pdf"
    assert await browser_page.locator("#privacy").is_checked()
    assert result.upload_evidence[0]["verification"] == "passed"
    assert await browser_page.evaluate("window.submitAttempts || 0") == 0
    assert not any(item.get("action") == "ats_submit_clicked" for item in log)


@pytest.mark.asyncio
async def test_workday_unknown_required_question_fails_closed(browser_page):
    await browser_page.set_content(
        f"""
        <form action="{SAFE_WORKDAY_URL}">
          <label for="mystery">Explain the unclassified quantum requirement</label>
          <textarea id="mystery" required></textarea>
          <button type="submit" data-automation-id="submitButton">Submit Application</button>
        </form>
        """
    )

    async def fill_step(surface, step_number):
        return await _fill_step_fields(
            surface,
            profile={"answer_policies": []},
            cover_letter="",
            resume_path="",
            log=[],
            step_number=step_number,
        )

    result = await run_ats_application_flow(
        browser_page,
        WorkdayAdapter(),
        fill_step=fill_step,
        dry_run=True,
        log=[],
    )
    assert result.success is False
    assert result.requires_manual_review is True
    assert result.review_items


@pytest.mark.asyncio
async def test_workday_validation_errors_block_progress(browser_page):
    await browser_page.set_content(
        f"""
        <form action="{SAFE_WORKDAY_URL}">
          <button id="next" type="button"
                  data-automation-id="bottom-navigation-next-button">Next</button>
        </form>
        <script>
          document.querySelector('#next').onclick = () => {
            document.body.insertAdjacentHTML(
              'afterbegin',
              '<div role="alert" data-automation-id="errorMessage">' +
              'Please complete the required field</div>'
            );
          };
        </script>
        """
    )

    async def fill_step(surface, step_number):
        return {
            "filled_count": 0,
            "review_items": [],
            "control_evidence": [],
            "upload_evidence": [],
            "control_passes": 1,
        }

    result = await run_ats_application_flow(
        browser_page,
        WorkdayAdapter(),
        fill_step=fill_step,
        dry_run=True,
        log=[],
    )
    assert result.success is False
    assert result.requires_manual_review is True
    assert result.validation_errors
    assert result.review_items[0]["reason_code"] == "validation_error"


@pytest.mark.asyncio
async def test_workday_login_and_account_creation_are_manual(browser_page):
    await browser_page.set_content(
        """
        <button data-automation-id="jobPostingApplyButton">Apply</button>
        <label for="password">Password</label>
        <input id="password" type="password" data-automation-id="password">
        """
    )
    login = await detect_workday_login_or_account_boundary(browser_page)
    assert login["reason_code"] == "login_required"
    assert login["details"]["credentials_entered"] is False

    await browser_page.set_content(
        """
        <button data-automation-id="jobPostingApplyButton">Apply</button>
        <button data-automation-id="createAccountLink">Create Account</button>
        """
    )
    account = await detect_workday_login_or_account_boundary(browser_page)
    assert account["reason_code"] == "account_creation_required"
    assert account["details"]["account_created"] is False
    assert account["details"]["bypass_attempted"] is False


@pytest.mark.asyncio
async def test_workday_confirmation_requires_explicit_evidence(browser_page):
    await browser_page.set_content(
        """
        <main data-automation-id="applicationConfirmation">
          Thank you for applying. Your application has been received.
        </main>
        """
    )
    evidence = await WorkdayAdapter().detect_confirmation(
        browser_page,
        before_url="https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/Ottawa/R-123",
        before_fingerprint="before",
    )
    assert evidence
    assert evidence[0].is_sufficient is True
    assert evidence[0].evidence_type == "confirmation_page"
