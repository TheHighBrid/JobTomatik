import os

import pytest
import pytest_asyncio

from app.services.ats_flow import run_ats_application_flow
from app.services.ats_lever import (
    LeverAdapter,
    inspect_lever_posting,
    parse_lever_job_url,
)
from app.services.ats_registry import detect_ats_adapter
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
        "scope": "platform",
        "scope_value": "lever",
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
            pytest.fail(f"Chromium is required for Lever certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def test_lever_url_parsing_and_official_posting_inspection():
    assert parse_lever_job_url(
        "https://jobs.lever.co/acme/00920f64-c95c-477b-abde-38cff569f80f/apply"
    ) == ("acme", "00920f64-c95c-477b-abde-38cff569f80f", "global")
    assert parse_lever_job_url(
        "https://jobs.eu.lever.co/acme/eu-posting-123"
    ) == ("acme", "eu-posting-123", "eu")
    assert parse_lever_job_url(
        "https://api.lever.co/v0/postings/acme/posting-123?mode=json"
    ) == ("acme", "posting-123", "global")

    report = inspect_lever_posting({
        "id": "posting-123",
        "text": "Risk Analyst",
        "categories": {"location": "Ottawa", "commitment": "Full-Time"},
        "description": "<p>Role</p>",
        "descriptionPlain": "Role",
        "hostedUrl": "https://jobs.lever.co/acme/posting-123",
        "applyUrl": "https://jobs.lever.co/acme/posting-123/apply",
    })

    assert report["posting_metadata_certified"] is True
    assert report["apply_url_matches_posting"] is True
    assert report["system_required_fields"] == ["name", "email"]
    assert report["custom_questions_exposed_by_official_api"] is False
    assert report["custom_questions_require_dom_inspection"] is True


@pytest.mark.asyncio
async def test_lever_detection_prefers_lever_adapter(page):
    await page.set_content(
        '<form class="application-form" action="https://jobs.lever.co/acme/posting/apply"></form>'
    )
    adapter = await detect_ats_adapter(page, "https://jobs.lever.co/acme/posting/apply")
    assert adapter.name == "lever"


@pytest.mark.asyncio
async def test_lever_single_page_upload_controls_and_dry_run_ready(page, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\nJobTomatik Lever certification fixture")

    await page.set_content(
        """
        <form class="application-form" action="https://jobs.lever.co/acme/posting-123/apply">
          <label for="resume">Resume/CV</label>
          <input id="resume" name="resume" type="file" accept=".pdf" required>

          <label for="name">Full name</label>
          <input id="name" name="name" required>
          <label for="email">Email</label>
          <input id="email" name="email" type="email" required>
          <label for="phone">Phone</label>
          <input id="phone" name="phone" required>

          <label for="location">Current location</label>
          <input id="location" role="combobox" aria-controls="location-options"
                 aria-expanded="false" aria-autocomplete="list" required>
          <div id="location-options" role="listbox" hidden></div>

          <label for="linkedin">LinkedIn URL</label>
          <input id="linkedin" name="urls[LinkedIn]" type="url" required>

          <fieldset>
            <legend>Are you legally authorized to work in Canada?</legend>
            <label><input type="radio" name="work-auth" value="yes" required>Yes</label>
            <label><input type="radio" name="work-auth" value="no">No</label>
          </fieldset>
          <label><input id="consent" type="checkbox" required>I certify this application is accurate</label>

          <fieldset>
            <legend>Gender Identity</legend>
            <label><input type="radio" name="gender" value="prefer">Prefer not to disclose</label>
          </fieldset>

          <button class="postings-btn" type="submit">Submit application</button>
        </form>
        <script>
          const input = document.querySelector('#location');
          const listbox = document.querySelector('#location-options');
          input.addEventListener('click', () => {
            input.setAttribute('aria-expanded', 'true');
            listbox.hidden = false;
            listbox.innerHTML = '<div role="option" data-value="Ottawa, Ontario, Canada">Ottawa, Ontario, Canada</div>';
            listbox.querySelector('[role="option"]').onclick = () => {
              input.value = 'Ottawa, Ontario, Canada';
              input.setAttribute('aria-expanded', 'false');
              listbox.hidden = true;
              input.dispatchEvent(new Event('change', {bubbles: true}));
            };
          });
          document.querySelector('.application-form').onsubmit = (event) => event.preventDefault();
        </script>
        """
    )

    profile = {
        "full_name": "Avery Certification",
        "email": "avery.certification@example.test",
        "phone": "+1 613 555 0199",
        "linkedin_url": "https://www.linkedin.com/in/avery-certification-test",
        "answer_policies": [
            policy(
                "custom.current_location", "Ottawa, Ontario, Canada",
                phrases=["current location"], policy_id=1,
            ),
            policy(
                "work_authorization", "Yes",
                category="work_authorization", sensitivity="legal", policy_id=2,
            ),
            policy(
                "terms_consent", "Yes",
                category="consent", sensitivity="legal", policy_id=3,
            ),
        ],
    }
    log = []
    adapter = LeverAdapter()

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
    assert result.steps_completed == 1
    assert await page.locator("#name").input_value() == "Avery Certification"
    assert await page.locator("#email").input_value() == "avery.certification@example.test"
    assert await page.locator("#location").input_value() == "Ottawa, Ontario, Canada"
    assert await page.locator("#resume").evaluate("(el) => el.files[0].name") == "resume.pdf"
    assert await page.locator("#consent").is_checked()
    assert result.upload_evidence[0]["verification"] == "passed"
    assert not await page.locator('input[name="gender"]').is_checked()
    assert not any(item["action"] == "ats_submit_clicked" for item in log)


@pytest.mark.asyncio
async def test_lever_unknown_required_custom_question_fails_closed(page):
    await page.set_content(
        """
        <form class="application-form" action="https://jobs.lever.co/acme/posting/apply">
          <label for="unknown">Describe the private internal code word</label>
          <input id="unknown" required>
          <button type="submit">Submit application</button>
        </form>
        """
    )
    adapter = LeverAdapter()

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
        page, adapter, fill_step=fill_step, dry_run=True, log=[]
    )
    assert result.success is False
    assert result.requires_manual_review is True
    assert result.review_items[0]["reason_code"] == "ambiguous_question"


@pytest.mark.asyncio
async def test_lever_validation_errors_block_progress(page):
    await page.set_content(
        """
        <form class="application-form" action="https://jobs.lever.co/acme/posting/apply">
          <button id="next" type="button">Continue</button>
        </form>
        <script>
          document.querySelector('#next').onclick = () => {
            document.querySelector('.application-form').insertAdjacentHTML(
              'afterbegin', '<div class="application-field-error">Please complete the required field</div>'
            );
          };
        </script>
        """
    )
    adapter = LeverAdapter()

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
async def test_lever_submit_requires_explicit_confirmation(page):
    await page.set_content(
        """
        <form class="application-form" action="https://jobs.lever.co/acme/posting/apply">
          <button type="submit">Submit application</button>
        </form>
        <script>
          document.querySelector('.application-form').onsubmit = (event) => {
            event.preventDefault();
            document.body.innerHTML = '<main class="application-confirmation">Thank you for applying. Your application has been submitted.</main>';
          };
        </script>
        """
    )
    adapter = LeverAdapter()

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
    assert result.confirmation_evidence[0]["is_sufficient"] is True
    assert result.confirmation_evidence[0]["evidence_type"] == "confirmation_page"


@pytest.mark.asyncio
async def test_lever_submit_without_confirmation_is_uncertain(page):
    await page.set_content(
        """
        <form class="application-form" action="https://jobs.lever.co/acme/posting/apply">
          <button type="submit">Submit application</button>
        </form>
        <script>
          document.querySelector('.application-form').onsubmit = (event) => event.preventDefault();
        </script>
        """
    )
    adapter = LeverAdapter()

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
