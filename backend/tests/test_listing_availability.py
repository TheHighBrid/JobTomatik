from __future__ import annotations

import pytest

from app.services.listing_availability import (
    classify_closed_listing_text,
    detect_closed_listing,
)


class _FakePage:
    def __init__(self, payload):
        self.url = payload.get("url", "https://www.linkedin.com/jobs/view/123")
        self.payload = payload

    async def evaluate(self, _script):
        return self.payload


def test_classify_linkedin_closed_listing_copy():
    assert (
        classify_closed_listing_text("No longer accepting applications")
        == "No longer accepting applications"
    )


def test_classify_french_closed_listing_copy():
    assert classify_closed_listing_text("Ce poste n’est plus disponible")


def test_absent_apply_button_is_not_treated_as_closed_listing():
    assert classify_closed_listing_text("Apply on the company website") is None
    assert classify_closed_listing_text("About the role and qualifications") is None


@pytest.mark.asyncio
async def test_visible_status_marks_listing_closed_without_retry_or_handoff():
    page = _FakePage({
        "url": "https://www.linkedin.com/jobs/view/123",
        "title": "Fraud Specialist | LinkedIn",
        "statuses": ["No longer accepting applications"],
        "headings": ["Fraud Specialist"],
        "buttons": [],
    })

    result = await detect_closed_listing(page)

    assert result is not None
    assert result["reason_code"] == "listing_closed"
    assert result["terminal"] is True
    assert result["retryable"] is False
    assert result["summary"] == "This job is no longer accepting applications."


@pytest.mark.asyncio
async def test_job_description_language_does_not_create_false_closed_result():
    page = _FakePage({
        "url": "https://www.linkedin.com/jobs/view/123",
        "title": "Fraud Specialist | LinkedIn",
        "statuses": [],
        "headings": ["Fraud Specialist", "About the role"],
        "buttons": ["Apply"],
    })

    assert await detect_closed_listing(page) is None
