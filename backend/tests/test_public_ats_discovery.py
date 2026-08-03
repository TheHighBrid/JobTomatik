import httpx
import pytest

from app.services.public_ats_discovery import (
    PublicATSDiscoveryError,
    discover_public_ats_target,
    normalize_ashby,
    normalize_greenhouse,
    normalize_lever,
    provider_request,
)


def test_provider_request_rejects_unsafe_identifier():
    with pytest.raises(PublicATSDiscoveryError):
        provider_request({"provider": "greenhouse", "identifier": "../tenant"})


def test_provider_request_uses_official_endpoints():
    greenhouse_url, greenhouse_params = provider_request(
        {"provider": "greenhouse", "identifier": "example-bank"}
    )
    lever_url, lever_params = provider_request(
        {"provider": "lever", "identifier": "example-bank"}
    )
    ashby_url, ashby_params = provider_request(
        {"provider": "ashby", "identifier": "example-bank"}
    )

    assert greenhouse_url.endswith("/v1/boards/example-bank/jobs")
    assert greenhouse_params == {"content": "true"}
    assert lever_url.endswith("/v0/postings/example-bank")
    assert lever_params == {"mode": "json"}
    assert ashby_url.endswith("/posting-api/job-board/example-bank")
    assert ashby_params is None


def test_provider_normalizers_create_namespaced_jobs():
    greenhouse = normalize_greenhouse(
        {
            "jobs": [
                {
                    "id": 11,
                    "title": "Fraud Investigator",
                    "absolute_url": "https://boards.greenhouse.io/example/jobs/11",
                    "location": {"name": "Ottawa, ON"},
                    "content": "<p>Investigate fraud and AML alerts.</p>",
                }
            ]
        },
        identifier="example",
        company="Example Bank",
        api_url="https://boards-api.greenhouse.io/v1/boards/example/jobs",
        fallback_job_type="full_time",
    )
    lever = normalize_lever(
        [
            {
                "id": "lev-1",
                "text": "AML Analyst",
                "hostedUrl": "https://jobs.lever.co/example/lev-1",
                "descriptionPlain": "Review AML cases.",
                "categories": {"location": "Remote, Canada", "commitment": "Full-time"},
            }
        ],
        identifier="example",
        company="Example Bank",
        api_url="https://api.lever.co/v0/postings/example",
        fallback_job_type=None,
    )
    ashby = normalize_ashby(
        {
            "jobs": [
                {
                    "id": "ash-1",
                    "title": "KYC Analyst",
                    "jobUrl": "https://jobs.ashbyhq.com/example/ash-1",
                    "location": "Toronto, ON",
                    "descriptionHtml": "<p>KYC and compliance operations.</p>",
                    "employmentType": "FullTime",
                }
            ]
        },
        identifier="example",
        company="Example Bank",
        api_url="https://api.ashbyhq.com/posting-api/job-board/example",
        fallback_job_type=None,
    )

    assert greenhouse[0]["external_id"] == "greenhouse:example:11"
    assert greenhouse[0]["raw_data"]["official_public_ats"] is True
    assert lever[0]["external_id"] == "lever:example:lev-1"
    assert lever[0]["job_type"] == "full_time"
    assert ashby[0]["external_id"] == "ashby:example:ash-1"
    assert ashby[0]["description"] == "KYC and compliance operations."


@pytest.mark.asyncio
async def test_discover_target_filters_and_retains_provenance():
    payload = {
        "jobs": [
            {
                "id": 101,
                "title": "Fraud Investigator",
                "absolute_url": "https://boards.greenhouse.io/example/jobs/101",
                "location": {"name": "Ottawa, ON"},
                "content": "<p>Fraud, AML, banking, and investigations.</p>",
            },
            {
                "id": 102,
                "title": "Software Engineer",
                "absolute_url": "https://boards.greenhouse.io/example/jobs/102",
                "location": {"name": "New York, NY"},
                "content": "<p>Platform engineering.</p>",
            },
        ]
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await discover_public_ats_target(
            {
                "provider": "greenhouse",
                "identifier": "example",
                "company": "Example Bank",
            },
            keywords="fraud investigator",
            location="Ottawa",
            job_type="full_time",
            limit=10,
            client=client,
        )

    assert len(jobs) == 1
    assert jobs[0]["title"] == "Fraud Investigator"
    assert jobs[0]["source"] == "greenhouse"
    assert jobs[0]["raw_data"]["provider_api_url"].endswith("/example/jobs")
    assert jobs[0]["raw_data"]["application_method"] == "external_url"
