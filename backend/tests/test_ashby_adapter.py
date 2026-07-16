import os

import pytest
import pytest_asyncio

from app.services.ats_ashby import (
    ASHBY_FORM_FIELD_TYPES,
    AshbyAdapter,
    inspect_ashby_form_definition,
    inspect_ashby_public_job,
    parse_ashby_job_url,
)
from app.services.ats_flow import run_ats_application_flow
from app.services.ats_registry import detect_ats_adapter
from app.services.form_filler_v3 import _fill_step_fields


POSTING_ID = "7458d4e9-da2e-47bd-98cb-adfda43d42b2"


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
        "scope_value": "ashbyhq.com",
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
                pytest.fail(f"Chromium is required for Ashby certification: {exc}")
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


def test_ashby_url_public_metadata_and_official_form_definition():
    assert parse_ashby_job_url(
        f"https://jobs.ashbyhq.com/ashby/{POSTING_ID}"
    ) == ("ashby", POSTING_ID)
    assert parse_ashby_job_url(
        f"https://jobs.ashbyhq.com/ashby/{POSTING_ID}/application"
    ) == ("ashby", POSTING_ID)

    public = inspect_ashby_public_job({
        "id": POSTING_ID,
        "title": "Engineering Manager - EU",
        "department": "Engineering",
        "team": "EMEA Engineering",
        "employmentType": "FullTime",
        "location": "Remote - European Union",
        "publishedAt": "2026-07-01T00:00:00Z",
        "isListed": True,
        "jobUrl": f"https://jobs.ashbyhq.com/ashby/{POSTING_ID}",
        "applyUrl": f"https://jobs.ashbyhq.com/ashby/{POSTING_ID}/application",
    })
    assert public["public_board_metadata_certified"] is True
    assert public["application_form_definition_exposed_by_public_feed"] is False
    assert public["official_form_definition_requires_jobs_read_permission"] is True

    fields = [{
        "field": {
            "id": f"field-{index}",
            "type": field_type,
            "path": f"custom_{index}",
            "title": f"Field {index}",
            "isNullable": field_type != "File",
        },
        "isRequired": field_type == "File",
    } for index, field_type in enumerate(sorted(ASHBY_FORM_FIELD_TYPES), start=1)]

    schema = inspect_ashby_form_definition({
        "success": True,
        "results": {
            "id": POSTING_ID,
            "applicationFormDefinition": {"fields": fields},
            "surveyFormDefinitions": [{
                "id": "survey-1",
                "formDefinition": {
                    "fields": [{
                        "field": {
                            "id": "survey-consent",
                            "type": "Boolean",
                            "path": "survey_consent",
                            "title": "Survey consent",
                            "isNullable": True,
                        },
                        "isRequired": False,
                    }]
                },
            }],
        },
    })
    assert schema["form_definition_certified"] is True
    assert schema["unsupported_fields"] == []
    assert schema["survey_form_count"] == 1
    assert len(schema["required_uploads"]) == 1


def test_ashby_unknown_official_field_type_is_not_certified():
    report = inspect_ashby_form_definition({
        "applicationFormDefinition": {
            "fields": [{
                "field": {
                    "type": "FutureQuantumControl",
                    "path": "custom_future",
                    "title": "Future field",
                },
                "isRequired": True,
            }]
        }
    })
    assert report["form_definition_certified"] is False
    assert report["unsupported_fields"][0]["field_type"] == "FutureQuantumControl"


@pytest.mark.asyncio
async def test_registry_detects_ashby_without_generic_form_false_positive(browser_page):
    await browser_page.set_content(
        f'<form action="https://jobs.ashbyhq.com/ashby/{POSTING_ID}/application"></form>'
    )
    adapter = await detect_ats_adapter(browser_page, "https://careers.example.test/job")
    assert adapter.name == "ashby"

    other = await browser_page.context.new_page()
    try:
        await other.set_content('<form class="application-form"></form>')
        generic = await detect_ats_adapter(other, "https://careers.example.test/job")
        assert generic.name == "generic"
    finally:
        await other.close()


@pytest.mark.asyncio
async def test_ashby_multistep_dynamic_upload_and_dry_run_ready(browser_page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nJobTomatik Ashby certification fixture")

    await browser_page.set_content(
        f"""
        <form id="ashby-application" action="https://jobs.ashbyhq.com/ashby/{POSTING_ID}/application">
          <section id="step-1">
            <label for="name">Name</label><input id="name" name="name" required>
            <label for="email">Email</label><input id="email" type="email" required>
            <label for="phone">Phone</label><input id="phone" required>
            <button id="next-1" type="button">Next</button>
          </section>
          <section id="step-2" hidden>
            <label for="auth">Are you legally authorized to work in Canada?</label>
            <select id="auth" required>
              <option value="">Select</option><option value="yes">Yes</option><option value="no">No</option>
            </select>
            <label for="why">Why are you interested in this role?</label><textarea id="why" required></textarea>
            <div id="conditional"></div>
            <label for="resume">Resume</label><input id="resume" type="file" accept=".pdf" required>
            <button id="next-2" type="button">Continue</button>
          </section>
          <section id="step-3" hidden>
            <label><input id="accurate" type="checkbox" required>I certify this application is accurate</label>
            <button id="submit" type="submit">Submit Application</button>
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
          document.querySelector('#ashby-application').onsubmit = (event) => event.preventDefault();
        </script>
        """
    )

    profile = {
        "full_name": "Avery Certification",
        "email": "avery.certification@example.test",
        "phone": "+1 613 555 0199",
        "answer_policies": [
            policy("work_authorization", "Yes", category="work_authorization", sensitivity="legal", policy_id=1),
            policy(
                "custom.ashby_interest",
                "Synthetic Ashby certification response. This form will not be submitted.",
                phrases=["why are you interested in this role"], policy_id=2,
            ),
            policy("custom.available_start_date", "2026-08-01", phrases=["available start date"], policy_id=3),
            policy("terms_consent", "Yes", category="consent", sensitivity="legal", policy_id=4),
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
        browser_page, AshbyAdapter(), fill_step=fill_step, dry_run=True, log=log
    )

    assert result.success is True
    assert result.ready_to_submit is True
    assert result.requires_manual_review is False
    assert result.steps_completed == 3
    assert await browser_page.locator("#name").input_value() == "Avery Certification"
    assert await browser_page.locator("#start").input_value() == "2026-08-01"
    assert await browser_page.locator("#resume").evaluate("(el) => el.files[0].name") == "resume.pdf"
    assert await browser_page.locator("#accurate").is_checked()
    assert result.upload_evidence[0]["verification"] == "passed"
    assert not any(item.get("action") == "ats_submit_clicked" for item in log)


@pytest.mark.asyncio
async def test_ashby_unknown_required_question_fails_closed(browser_page):
    await browser_page.set_content(
        f"""
        <form action="https://jobs.ashbyhq.com/ashby/{POSTING_ID}/application">
          <label for="mystery">Explain the unclassified quantum requirement</label>
          <textarea id="mystery" required></textarea>
          <button type="submit">Submit Application</button>
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
        browser_page, AshbyAdapter(), fill_step=fill_step, dry_run=True, log=[]
    )
    assert result.success is False
    assert result.requires_manual_review is True
    assert result.review_items


@pytest.mark.asyncio
async def test_ashby_validation_errors_block_progress(browser_page):
    await browser_page.set_content(
        f"""
        <form action="https://jobs.ashbyhq.com/ashby/{POSTING_ID}/application">
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
        browser_page, AshbyAdapter(), fill_step=empty_fill, dry_run=True, log=[]
    )
    assert result.requires_manual_review is True
    assert result.review_items[0]["reason_code"] == "validation_error"


@pytest.mark.asyncio
async def test_ashby_confirmation_and_uncertain_submission_paths(browser_page):
    async def empty_fill(surface, step_number):
        return {"filled_count": 0, "review_items": [], "control_evidence": [], "upload_evidence": []}

    await browser_page.set_content(
        f"""
        <form id="application" action="https://jobs.ashbyhq.com/ashby/{POSTING_ID}/application">
          <button type="submit">Submit Application</button>
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
        browser_page, AshbyAdapter(), fill_step=empty_fill, dry_run=False, log=[]
    )
    assert confirmed.success is True
    assert confirmed.confirmation_evidence[0]["is_sufficient"] is True

    await browser_page.set_content(
        f"""
        <form id="application" action="https://jobs.ashbyhq.com/ashby/{POSTING_ID}/application">
          <button type="submit">Submit Application</button>
        </form>
        <script>document.querySelector('#application').onsubmit = (event) => event.preventDefault();</script>
        """
    )
    uncertain = await run_ats_application_flow(
        browser_page, AshbyAdapter(), fill_step=empty_fill, dry_run=False, log=[]
    )
    assert uncertain.success is False
    assert uncertain.requires_manual_review is True
    assert uncertain.review_items[0]["reason_code"] == "submission_confirmation_uncertain"
