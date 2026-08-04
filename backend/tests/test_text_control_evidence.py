import json
import os

import pytest
import pytest_asyncio

from app.services import form_filler_v3
from app.services.lever_certification import _synthetic_policy
from app.services.text_control_evidence import install_text_control_evidence


install_text_control_evidence()


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
            pytest.fail(f"Chromium is required for text-evidence certification: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def _assert_redacted(evidence, raw_value):
    assert evidence["action"] == "control_verified"
    assert evidence["verification"] == "passed"
    assert evidence["value_redacted"] is True
    assert evidence["selected"] == []
    assert raw_value not in json.dumps(evidence, sort_keys=True)


@pytest.mark.asyncio
async def test_verified_profile_text_fill_retains_redacted_control_evidence(page):
    synthetic_email = "phase-a-day13@example.invalid"
    await page.set_content(
        '<label for="candidate-email">Email</label>'
        '<input id="candidate-email" name="email" type="email" required>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={"email": synthetic_email, "answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert outcome["filled_count"] == 1
    assert len(outcome["control_evidence"]) == 1
    evidence = outcome["control_evidence"][0]
    assert evidence["canonical_key"] == "profile.email"
    assert evidence["source"] == "profile"
    assert evidence["policy_id"] is None
    _assert_redacted(evidence, synthetic_email)


@pytest.mark.asyncio
async def test_prepopulated_profile_text_still_retains_evidence(page):
    synthetic_email = "prepopulated@example.invalid"
    await page.set_content(
        f'<label for="email">Email</label>'
        f'<input id="email" name="email" type="email" value="{synthetic_email}" required>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={"email": synthetic_email, "answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert outcome["filled_count"] == 0
    assert len(outcome["control_evidence"]) == 1
    assert outcome["control_evidence"][0]["prepopulated"] is True
    _assert_redacted(outcome["control_evidence"][0], synthetic_email)


@pytest.mark.asyncio
async def test_policy_text_evidence_retains_resolved_policy_id(page):
    answer = "Synthetic certification response."
    descriptor = "Why are you interested in this role?"
    policy = _synthetic_policy(
        77,
        canonical_key="custom.why_role",
        category="synthetic_certification",
        sensitivity="synthetic",
        answer=answer,
        descriptor=descriptor,
    )
    await page.set_content(
        '<label for="why">Why are you interested in this role?</label>'
        '<textarea id="why" name="why" required></textarea>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={"answer_policies": [policy]},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert len(outcome["control_evidence"]) == 1
    evidence = outcome["control_evidence"][0]
    assert evidence["source"] == "answer_policy"
    assert evidence["policy_id"] == 77
    _assert_redacted(evidence, answer)


@pytest.mark.asyncio
async def test_repeated_text_controls_keep_distinct_identities(page):
    raw_value = "Synthetic Candidate"
    await page.set_content(
        '<label for="name-a">Full name</label><input id="name-a" required>'
        '<label for="name-b">Full name</label><input id="name-b" required>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={"full_name": raw_value, "answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    evidence = [
        item for item in outcome["control_evidence"]
        if item.get("canonical_key") == "profile.full_name"
    ]
    assert len(evidence) == 2
    assert len({item["control_id"] for item in evidence}) == 2
    for item in evidence:
        _assert_redacted(item, raw_value)


@pytest.mark.asyncio
async def test_text_evidence_installer_is_idempotent(page):
    install_text_control_evidence()
    install_text_control_evidence()
    await page.set_content(
        '<label for="name">Full name</label><input id="name" required>'
    )

    outcome = await form_filler_v3._fill_step_fields(
        page,
        profile={"full_name": "Synthetic Candidate", "answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    evidence = [
        item for item in outcome["control_evidence"]
        if item.get("canonical_key") == "profile.full_name"
    ]
    assert len(evidence) == 1
