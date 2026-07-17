import os

import pytest
import pytest_asyncio

# Importing the public form-filler entrypoint installs the compatibility wrappers.
from app.services import form_filler as _form_filler  # noqa: F401
from app.services.control_engine import element_descriptor
from app.services.greenhouse_phone_widget import (
    _phone_fill_candidates,
    _reconcile_phone_review,
)


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
            pytest.fail(f"Chromium is required for Greenhouse phone tests: {exc}")
        pytest.skip("Chromium is not installed in this environment")
    page = await browser.new_page()
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def _phone_review(descriptor: str):
    return {
        "reason_code": "unsupported_control",
        "summary": f"Profile field could not be verified: {descriptor}",
        "details": {
            "canonical_key": "profile.phone",
            "category": "profile",
            "descriptor": descriptor,
            "control_type": "text",
            "required": True,
        },
    }


def test_canadian_phone_candidates_include_e164_representation():
    candidates = _phone_fill_candidates(
        {"country": "Canada"},
        "6135550199",
    )

    assert candidates == ["6135550199", "+16135550199"]


@pytest.mark.asyncio
async def test_phone_retry_uses_e164_when_widget_rejects_national_number(page):
    await page.set_content(
        r"""
        <label for="phone">Phone</label>
        <input id="phone" name="phone" type="tel" required>
        <script>
          const phone = document.querySelector('#phone');
          phone.addEventListener('input', () => {
            const digits = phone.value.replace(/\D/g, '');
            if (!phone.value.startsWith('+1') || digits.length !== 11) {
              phone.value = '';
              return;
            }
            phone.value = `+1 (${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
          });
        </script>
        """
    )
    element = await page.query_selector("#phone")
    descriptor = await element_descriptor(page, element)
    review_items = [_phone_review(descriptor)]
    log = []
    profile = {
        "full_name": "Avery Certification",
        "first_name": "Avery",
        "last_name": "Certification",
        "email": "avery.certification@example.test",
        "phone": "6135550199",
        "country": "Canada",
        "answer_policies": [],
    }

    count = await _reconcile_phone_review(
        page,
        profile=profile,
        cover_letter="",
        log=log,
        review_items=review_items,
    )

    assert count == 1
    assert review_items == []
    assert await element.input_value() == "+1 (613) 555-0199"
    assert any(
        item.get("action") == "phone_format_verified"
        and item.get("fill_method") in {"fill", "type", "native_setter"}
        for item in log
    )
