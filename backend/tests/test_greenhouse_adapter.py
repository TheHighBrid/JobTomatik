import os

import pytest
import pytest_asyncio

from app.services.ats_flow import run_ats_application_flow
from app.services.ats_greenhouse import (
    GreenhouseAdapter,
    inspect_greenhouse_schema,
    parse_greenhouse_job_url,
)
from app.services.form_filler_v3 import _fill_step_fields


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
        "scope": "global",
        "scope_value": "",
        "allow_autofill": True,
        "is_active": True,
        "confirmed_at": "2026-07-15T10:00:00",
    }


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
            pytest.fail(f"Chromium is required for Greenhouse certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def test_greenhouse_url_parsing_and_schema_inspection():
    assert parse_greenhouse_job_url(
        "https://job-boards.greenhouse.io/acme/jobs/1234567"
    ) == ("acme", "1234567")
    assert parse_greenhouse_job_url(
        "https://boards.greenhouse.io/acme/jobs/7654321"
    ) == ("acme", "7654321")

    report = inspect_greenhouse_schema({
        "id": 123,
        "title": "Analyst",
        "company_name": "Acme",
        "questions": [
            {
                "label": "Resume",
                "required": True,
                "fields": [
                    {"name": "resume", "type": "input_file"},
                    {"name": "resume_text", "type": "textarea"},
                ],
            },
            {
                "label": "Work authorization",
                "required": True,
                "fields": [{
                    "name": "question_1",
                    "type": "multi_value_single_select",
                    "values": [{"value": 1, "label": "Yes"}],
                }],
            },
        ],
        "demographic_questions": {
            "questions": [{
                "id": 9,
                "label": "Voluntary question",
                "required": False,
                "type": "multi_value_multi_select",
                "answer_options": [{"id": 1, "label": "Prefer not to say"}],
            }]
        },
        "data_compliance": [{"type": "gdpr", "requires_consent": True}],
    })

    assert report["schema_certified"] is True
    assert report["question_count"] == 3
    assert report["required_uploads"] == ["Resume"]
    assert report["unsupported_fields"] == []


def test_greenhouse_schema_accepts_list_demographic_payloads():
    report = inspect_greenhouse_schema({
        "id": 456,
        "questions": [],
        "demographic_questions": [{
            "id": 12,
            "label": "Gender",
            "required": False,
            "type": "multi_value_single_select",
            "answer_options": [{"id": 1, "label": "Prefer not to say"}],
        }],
        "compliance": [{"type": "gdpr"}],
    })

    assert report["schema_certified"] is True
    assert report["question_count"] == 1
    assert report["questions"][0]["source"] == "demographic_questions"
    assert report["data_compliance"] == [{"type": "gdpr"}]


@pytest.mark.asyncio
async def test_greenhouse_multistep_dynamic_upload_and_dry_run_ready(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nJobTomatik certification fixture")

    await page.set_content(
        """
        <form id="application_form" action="https://boards.greenhouse.io/acme/jobs/123">
          <section id="step-1">
            <label for="first">First Name</label>
            <input id="first" name="first_name" required>
            <label for="last">Last Name</label>
            <input id="last" name="last_name" required>
            <label for="email">Email</label>
            <input id="email" name="email" required>
            <button id="next-1" type="button">Next</button>
          </section>
          <section id="step-2" hidden>
            <label for="auth">Are you legally authorized to work in Canada?</label>
            <select id="auth" required>
              <option value="">Select</option><option value="yes">Yes</option><option value="no">No</option>
            </select>
            <fieldset>
              <legend>Are you willing to relocate?</legend>
              <label><input type="radio" name="relocate" value="yes" required>Yes</label>
              <label><input type="radio" name="relocate" value="no">No</label>
            </fieldset>
            <div id="conditional"></div>
            <label for="resume">Resume</label>
            <input id="resume" type="file" accept=".pdf" required>
            <button id="next-2" type="button">Continue</button>
          </section>
          <section id="step-3" hidden>
            <label><input id="terms" type="checkbox" required>I certify this application is accurate</label>
            <button id="submit_app" type="submit">Submit Application</button>
          </section>
        </form>
        <script>
          next1 = document.querySelector('#next-1');
          next2 = document.querySelector('#next-2');
          next1.onclick = () => {
            document.querySelector('#step-1').hidden = true;
            document.querySelector('#step-2').hidden = false;
          };
          document.querySelectorAll('input[name="relocate"]').forEach((radio) => {
            radio.onchange = () => {
              if (radio.checked && radio.value === 'yes') {
                document.querySelector('#conditional').innerHTML =
                  '<label for="city">Preferred relocation city</label><input id="city" required>';
              }
            };
          });
          next2.onclick = () => {
            document.querySelector('#step-2').hidden = true;
            document.querySelector('#step-3').hidden = false;
          };
          document.querySelector('#application_form').onsubmit = (event) => event.preventDefault();
        </script>
        """
    )

    profile = {
        "full_name": "Test Candidate",
        "email": "candidate@example.test",
        "answer_policies": [
            policy(
                "work_authorization", "Yes",
                category="work_authorization", sensitivity="legal", policy_id=1,
            ),
            policy("willing_to_relocate", "Yes", category="relocation", policy_id=2),
            policy(
                "custom.relocation_city", "Montreal",
                phrases=["preferred relocation city"], policy_id=3,
            ),
            policy(
                "terms_consent", "Yes",
                category="consent", sensitivity="legal", policy_id=4,
            ),
        ],
    }
    log = []
    adapter = GreenhouseAdapter()

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
        page, adapter, fill_step=fill_step, dry_run=True, log=log
    )

    assert result.success is True
    assert result.ready_to_submit is True
    assert result.requires_manual_review is False
    assert result.steps_completed == 3
    assert await page.locator("#city").input_value() == "Montreal"
    assert await page.locator("#resume").evaluate("(el) => el.files[0].name") == "resume.pdf"
    assert await page.locator("#terms").is_checked()
    assert result.upload_evidence[0]["verification"] == "passed"
    assert not any(item["action"] == "ats_submit_clicked" for item in log)


@pytest.mark.asyncio
async def test_greenhouse_validation_errors_block_progress(page):
    await page.set_content(
        """
        <form id="application_form" action="https://boards.greenhouse.io/acme/jobs/123">
          <div id="step">
            <button id="next" type="button">Next</button>
          </div>
          <script>
            document.querySelector('#next').onclick = () => {
              document.querySelector('#step').insertAdjacentHTML(
                'afterbegin', '<div role="alert">Please complete the required field</div>'
              );
            };
          </script>
        </form>
        """
    )
    adapter = GreenhouseAdapter()

    async def empty_fill(surface, step_number):
        return {
            "filled_count": 0,
            "review_items": [],
            "control_evidence": [],
            "upload_evidence": [],
        }

    result = await run_ats_application_flow(
        page, adapter, fill_step=empty_fill, dry_run=True, log=[]
    )

    assert result.success is False
    assert result.requires_manual_review is True
    assert result.review_items[0]["reason_code"] == "validation_error"
    assert "required field" in result.validation_errors[0]["message"]


@pytest.mark.asyncio
async def test_greenhouse_local_submit_requires_confirmation(page):
    await page.set_content(
        """
        <form id="application_form" action="https://boards.greenhouse.io/acme/jobs/123">
          <button id="submit_app" type="submit">Submit Application</button>
        </form>
        <script>
          document.querySelector('#application_form').onsubmit = (event) => {
            event.preventDefault();
            document.body.innerHTML =
              '<main id="application_confirmation">Thank you for applying. Your application has been received.</main>';
          };
        </script>
        """
    )
    adapter = GreenhouseAdapter()

    async def empty_fill(surface, step_number):
        return {
            "filled_count": 0,
            "review_items": [],
            "control_evidence": [],
            "upload_evidence": [],
        }

    result = await run_ats_application_flow(
        page, adapter, fill_step=empty_fill, dry_run=False, log=[]
    )

    assert result.success is True
    assert result.requires_manual_review is False
    assert result.confirmation_evidence[0]["is_sufficient"] is True
    assert result.confirmation_evidence[0]["evidence_type"] == "confirmation_page"


@pytest.mark.asyncio
async def test_greenhouse_submit_without_confirmation_is_uncertain(page):
    await page.set_content(
        """
        <form id="application_form" action="https://boards.greenhouse.io/acme/jobs/123">
          <button id="submit_app" type="submit">Submit Application</button>
        </form>
        <script>
          document.querySelector('#application_form').onsubmit = (event) => event.preventDefault();
        </script>
        """
    )
    adapter = GreenhouseAdapter()

    async def empty_fill(surface, step_number):
        return {
            "filled_count": 0,
            "review_items": [],
            "control_evidence": [],
            "upload_evidence": [],
        }

    result = await run_ats_application_flow(
        page, adapter, fill_step=empty_fill, dry_run=False, log=[]
    )

    assert result.success is False
    assert result.requires_manual_review is True
    assert result.review_items[0]["reason_code"] == "submission_confirmation_uncertain"
