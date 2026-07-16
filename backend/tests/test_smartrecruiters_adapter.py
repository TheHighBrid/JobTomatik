import os

import pytest
import pytest_asyncio

from app.services.ats_flow import run_ats_application_flow
from app.services.ats_registry import detect_ats_adapter
from app.services.ats_smartrecruiters import (
    SMARTRECRUITERS_SCREENING_FIELD_TYPES,
    SmartRecruitersAdapter,
    inspect_smartrecruiters_configuration,
    inspect_smartrecruiters_posting,
    parse_smartrecruiters_job_url,
)
from app.services.form_filler_v3 import _fill_step_fields


POSTING_ID = "744000137613800"
POSTING_UUID = "846c9735-28eb-464c-b3aa-4c0407979e0f"
COMPANY = "smartrecruiters"


def policy(key, answer, *, phrases=None, category="custom", sensitivity="standard", policy_id=1):
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
        "scope_value": "smartrecruiters.com",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-15T10:00:00",
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
                pytest.fail(f"Chromium is required for SmartRecruiters certification: {exc}")
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


def test_smartrecruiters_url_metadata_and_official_configuration():
    assert parse_smartrecruiters_job_url(
        f"https://jobs.smartrecruiters.com/{COMPANY}/{POSTING_ID}-security-engineer"
    ) == (COMPANY, POSTING_ID, "hosted_job")
    assert parse_smartrecruiters_job_url(
        f"https://jobs.smartrecruiters.com/oneclick-ui/company/{COMPANY}/publication/{POSTING_UUID}"
    ) == (COMPANY, POSTING_UUID, "oneclick_application")
    assert parse_smartrecruiters_job_url(
        f"https://api.smartrecruiters.com/v1/companies/{COMPANY}/postings/{POSTING_ID}"
    ) == (COMPANY, POSTING_ID, "api_posting")
    assert parse_smartrecruiters_job_url(
        f"https://careers.smartrecruiters.com/{COMPANY}"
    ) == (COMPANY, None, "career_site")

    public = inspect_smartrecruiters_posting({
        "id": POSTING_ID,
        "uuid": POSTING_UUID,
        "name": "Senior Information Security Engineer",
        "company": {"identifier": COMPANY, "name": "SmartRecruiters Inc"},
        "releasedDate": "2026-07-14T08:29:20.852Z",
        "location": {"country": "pl", "remote": True},
        "ref": f"https://api.smartrecruiters.com/v1/companies/{COMPANY}/postings/{POSTING_ID}",
        "applyUrl": (
            f"https://jobs.smartrecruiters.com/oneclick-ui/company/{COMPANY}/"
            f"publication/{POSTING_UUID}"
        ),
        "active": True,
    })
    assert public["posting_metadata_certified"] is True
    assert public["screening_configuration_public"] is False
    assert public["screening_configuration_requires_smart_token"] is True

    questions = []
    for index, field_type in enumerate(sorted(SMARTRECRUITERS_SCREENING_FIELD_TYPES), start=1):
        questions.append({
            "id": f"question-{index}",
            "label": f"Question {index}",
            "repeatable": field_type == "INPUT_TEXT",
            "fields": [{
                "id": "value",
                "label": f"Field {index}",
                "type": field_type,
                "required": field_type not in {"INFORMATION"},
                "complianceType": "DIVERSITY" if field_type == "RADIO" else None,
                "values": (
                    [{"id": "yes", "label": "Yes"}, {"id": "no", "label": "No"}]
                    if field_type in {"SINGLE_SELECT", "MULTI_SELECT", "RADIO", "CHECKBOX"}
                    else []
                ),
            }],
        })
    report = inspect_smartrecruiters_configuration({
        "questions": questions,
        "settings": {
            "avatarUploadAvailable": False,
            "conditionals": [{
                "parentQuestionId": "question-3",
                "fieldId": "value",
                "valueIds": ["yes"],
                "conditionalQuestions": ["question-4"],
            }],
        },
        "privacyPolicies": [
            {"url": "https://example.test/privacy", "orgName": "Example"}
        ],
    })
    assert report["configuration_certified"] is True
    assert report["unsupported_fields"] == []
    assert report["conditional_count"] == 1
    assert report["privacy_policy_count"] == 1
    assert report["diversity_fields"]


def test_smartrecruiters_unknown_official_field_or_invalid_conditional_fails_certification():
    report = inspect_smartrecruiters_configuration({
        "questions": [{
            "id": "known-question",
            "label": "Future field",
            "fields": [{
                "id": "value",
                "type": "FUTURE_QUANTUM_CONTROL",
                "required": True,
                "values": [],
            }],
        }],
        "settings": {
            "conditionals": [{
                "parentQuestionId": "missing-question",
                "fieldId": "value",
                "valueIds": ["yes"],
                "conditionalQuestions": ["known-question"],
            }]
        },
        "privacyPolicies": [],
    })
    assert report["configuration_certified"] is False
    assert report["unsupported_fields"][0]["field_type"] == "FUTURE_QUANTUM_CONTROL"
    assert report["invalid_conditionals"]


@pytest.mark.asyncio
async def test_registry_detects_smartrecruiters_without_generic_false_positive(browser_page):
    await browser_page.set_content(
        f'<form action="https://jobs.smartrecruiters.com/oneclick-ui/company/{COMPANY}/publication/{POSTING_UUID}"></form>'
    )
    adapter = await detect_ats_adapter(browser_page, "https://careers.example.test/job")
    assert adapter.name == "smartrecruiters"

    other = await browser_page.context.new_page()
    try:
        await other.set_content('<form class="application-form"></form>')
        generic = await detect_ats_adapter(other, "https://careers.example.test/job")
        assert generic.name == "generic"
    finally:
        await other.close()


@pytest.mark.asyncio
async def test_smartrecruiters_multistep_dynamic_upload_and_dry_run_ready(browser_page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nJobTomatik SmartRecruiters certification fixture")

    await browser_page.set_content(
        f"""
        <form id="smartrecruiters-application" action="https://jobs.smartrecruiters.com/oneclick-ui/company/{COMPANY}/publication/{POSTING_UUID}">
          <section id="step-1">
            <label for="first-name">First Name</label><input id="first-name" required>
            <label for="last-name">Last Name</label><input id="last-name" required>
            <label for="email">Email</label><input id="email" type="email" required>
            <label for="phone">Phone</label><input id="phone" required>
            <button id="next-1" type="button">Next</button>
          </section>
          <section id="step-2" hidden>
            <label for="auth">Are you legally authorized to work in Canada?</label>
            <select id="auth" required>
              <option value="">Select</option><option value="yes">Yes</option><option value="no">No</option>
            </select>
            <label for="interest">Why are you interested in this role?</label><textarea id="interest" required></textarea>
            <div id="conditional"></div>
            <label for="resume">Resume</label><input id="resume" type="file" accept=".pdf" required>
            <button id="next-2" type="button">Continue</button>
          </section>
          <section id="step-3" hidden>
            <label><input id="privacy" type="checkbox" required>I agree to the privacy policy</label>
            <button id="submit" type="submit">Submit application</button>
          </section>
        </form>
        <script>
          document.querySelector('#next-1').onclick = () => {{
            document.querySelector('#step-1').hidden = true;
            document.querySelector('#step-2').hidden = false;
          }};
          document.querySelector('#auth').onchange = (event) => {{
            if (event.target.value === 'yes') {{
              document.querySelector('#conditional').innerHTML =
                '<label for="start">Available start date</label><input id="start" type="date" required>';
            }}
          }};
          document.querySelector('#next-2').onclick = () => {{
            document.querySelector('#step-2').hidden = true;
            document.querySelector('#step-3').hidden = false;
          }};
          document.querySelector('#smartrecruiters-application').onsubmit = (event) => event.preventDefault();
        </script>
        """
    )

    profile = {
        "full_name": "Avery Certification",
        "first_name": "Avery",
        "last_name": "Certification",
        "email": "avery.certification@example.test",
        "phone": "+1 613 555 0199",
        "answer_policies": [
            policy("work_authorization", "Yes", category="work_authorization", sensitivity="legal", policy_id=1),
            policy(
                "custom.smartrecruiters_interest",
                "Synthetic SmartRecruiters certification response. This form will not be submitted.",
                phrases=["why are you interested in this role"], policy_id=2,
            ),
            policy("custom.available_start_date", "2026-08-01", phrases=["available start date"], policy_id=3),
            policy("privacy_consent", "Yes", category="consent", sensitivity="legal", policy_id=4),
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
        SmartRecruitersAdapter(),
        fill_step=fill_step,
        dry_run=True,
        log=log,
    )

    assert result.success is True
    assert result.ready_to_submit is True
    assert result.requires_manual_review is False
    assert result.steps_completed == 3
    assert await browser_page.locator("#first-name").input_value() == "Avery"
    assert await browser_page.locator("#last-name").input_value() == "Certification"
    assert await browser_page.locator("#start").input_value() == "2026-08-01"
    assert await browser_page.locator("#resume").evaluate("(el) => el.files[0].name") == "resume.pdf"
    assert await browser_page.locator("#privacy").is_checked()
    assert result.upload_evidence[0]["verification"] == "passed"
    assert not any(item.get("action") == "ats_submit_clicked" for item in log)


@pytest.mark.asyncio
async def test_smartrecruiters_unknown_required_question_fails_closed(browser_page):
    await browser_page.set_content(
        f"""
        <form action="https://jobs.smartrecruiters.com/oneclick-ui/company/{COMPANY}/publication/{POSTING_UUID}">
          <label for="mystery">Explain the unclassified quantum requirement</label>
          <textarea id="mystery" required></textarea>
          <button type="submit">Submit application</button>
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
        SmartRecruitersAdapter(),
        fill_step=fill_step,
        dry_run=True,
        log=[],
    )
    assert result.success is False
    assert result.requires_manual_review is True
    assert result.review_items


@pytest.mark.asyncio
async def test_smartrecruiters_validation_errors_block_progress(browser_page):
    await browser_page.set_content(
        f"""
        <form action="https://jobs.smartrecruiters.com/oneclick-ui/company/{COMPANY}/publication/{POSTING_UUID}">
          <button id="next" type="button">Next</button>
        </form>
        <script>
          document.querySelector('#next').onclick = () => {{
            document.body.insertAdjacentHTML('afterbegin', '<div role="alert">Please complete the required field</div>');
          }};
        </script>
        """
    )

    async def empty_fill(surface, step_number):
        return {"filled_count": 0, "review_items": [], "control_evidence": [], "upload_evidence": []}

    result = await run_ats_application_flow(
        browser_page,
        SmartRecruitersAdapter(),
        fill_step=empty_fill,
        dry_run=True,
        log=[],
    )
    assert result.requires_manual_review is True
    assert result.review_items[0]["reason_code"] == "validation_error"


@pytest.mark.asyncio
async def test_smartrecruiters_confirmation_and_uncertain_submission_paths(browser_page):
    async def empty_fill(surface, step_number):
        return {"filled_count": 0, "review_items": [], "control_evidence": [], "upload_evidence": []}

    await browser_page.set_content(
        f"""
        <form id="application" action="https://jobs.smartrecruiters.com/oneclick-ui/company/{COMPANY}/publication/{POSTING_UUID}">
          <button type="submit">Submit application</button>
        </form>
        <script>
          document.querySelector('#application').onsubmit = (event) => {{
            event.preventDefault();
            document.body.innerHTML = '<main data-testid="application-confirmation">Thank you for applying. Your application has been received.</main>';
          }};
        </script>
        """
    )
    confirmed = await run_ats_application_flow(
        browser_page,
        SmartRecruitersAdapter(),
        fill_step=empty_fill,
        dry_run=False,
        log=[],
    )
    assert confirmed.success is True
    assert confirmed.confirmation_evidence[0]["is_sufficient"] is True

    await browser_page.set_content(
        f"""
        <form id="application" action="https://jobs.smartrecruiters.com/oneclick-ui/company/{COMPANY}/publication/{POSTING_UUID}">
          <button type="submit">Submit application</button>
        </form>
        <script>document.querySelector('#application').onsubmit = (event) => event.preventDefault();</script>
        """
    )
    uncertain = await run_ats_application_flow(
        browser_page,
        SmartRecruitersAdapter(),
        fill_step=empty_fill,
        dry_run=False,
        log=[],
    )
    assert uncertain.success is False
    assert uncertain.requires_manual_review is True
    assert uncertain.review_items[0]["reason_code"] == "submission_confirmation_uncertain"
