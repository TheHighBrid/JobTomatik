import inspect
import json
import os
import re

import pytest
import pytest_asyncio

from app.services import form_filler_v3
from app.services.form_filler_v3 import _fill_step_fields
from app.services.greenhouse_phone_widget import (
    install_greenhouse_phone_widget_compat,
)
from app.services.lever_certification import _synthetic_policy


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


def assert_redacted(evidence, raw_value):
    assert evidence["action"] == "text_fill_verified"
    assert evidence["verification"] == "passed"
    assert evidence["verification_method"] == "browser_input_value_readback"
    assert evidence["value_length"] == len(raw_value)
    assert re.fullmatch(r"[0-9a-f]{64}", evidence["value_sha256"])
    assert raw_value not in json.dumps(evidence, sort_keys=True)


@pytest.mark.asyncio
async def test_profile_text_field_emits_redacted_verified_evidence(page):
    raw_value = "Avery Certification"
    await page.set_content(
        '<label for="name">Full name</label>'
        '<input id="name" name="name" required>'
    )

    outcome = await _fill_step_fields(
        page,
        profile={"full_name": raw_value, "answer_policies": []},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert outcome["review_items"] == []
    assert outcome["filled_count"] == 1
    assert len(outcome["control_evidence"]) == 1
    evidence = outcome["control_evidence"][0]
    assert evidence["source"] == "profile"
    assert evidence["canonical_key"] == "profile.full_name"
    assert evidence["policy_id"] is None
    assert evidence["control_type"] == "text"
    assert await page.locator("#name").input_value() == raw_value
    assert_redacted(evidence, raw_value)


@pytest.mark.asyncio
async def test_policy_textarea_emits_one_redacted_evidence_record(page):
    raw_value = "Synthetic certification response that is never submitted."
    descriptor = "Why are you interested in this role?"
    policy = _synthetic_policy(
        77,
        canonical_key="custom.why_role",
        category="synthetic_certification",
        sensitivity="synthetic",
        answer=raw_value,
        descriptor=descriptor,
    )
    await page.set_content(
        '<label for="why">Why are you interested in this role?</label>'
        '<textarea id="why" name="why" required></textarea>'
    )

    outcome = await _fill_step_fields(
        page,
        profile={"answer_policies": [policy]},
        cover_letter="",
        resume_path="",
        log=[],
        step_number=1,
    )

    assert outcome["review_items"] == []
    assert outcome["filled_count"] == 1
    assert len(outcome["control_evidence"]) == 1
    evidence = outcome["control_evidence"][0]
    assert evidence["source"] == "answer_policy"
    assert evidence["canonical_key"] == "custom.why_role"
    assert evidence["policy_id"] == 77
    assert evidence["control_type"] == "textarea"
    assert await page.locator("#why").input_value() == raw_value
    assert_redacted(evidence, raw_value)


def test_phone_widget_compat_forwards_text_evidence_argument():
    install_greenhouse_phone_widget_compat()
    signature = inspect.signature(form_filler_v3._fill_text_fields)
    assert "control_evidence" in signature.parameters
