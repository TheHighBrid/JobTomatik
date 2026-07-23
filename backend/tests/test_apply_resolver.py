import pytest

from app.services.apply_resolver import resolve_application_method


@pytest.mark.asyncio
async def test_linkedin_listing_is_routed_to_browser_navigation():
    url = "https://www.linkedin.com/jobs/view/bilingual-fraud-advisor-at-rbc-4439524897/"

    result = await resolve_application_method(url)

    assert result["application_method"] == "external_url"
    assert result["selected_apply_url"] == url
    assert result["listing_navigation_required"] is True
    assert "outbound" in result["reason"].lower()


@pytest.mark.asyncio
async def test_indeed_listing_remains_unsupported():
    url = "https://ca.indeed.com/viewjob?jk=example"

    result = await resolve_application_method(url)

    assert result["application_method"] == "unsupported_job_board"
    assert "indeed" in result["reason"].lower()
