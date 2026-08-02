import pytest

from app.services import discovery_search


@pytest.mark.asyncio
async def test_explicit_empty_source_list_searches_nothing(monkeypatch):
    broad_called = False
    ats_called = False

    async def fake_broad(**kwargs):
        nonlocal broad_called
        broad_called = True
        return []

    async def fake_ats(*args, **kwargs):
        nonlocal ats_called
        ats_called = True
        return []

    monkeypatch.setattr(discovery_search, "search_broad_jobs", fake_broad)
    monkeypatch.setattr(discovery_search, "discover_public_ats_target", fake_ats)

    result = await discovery_search.search_jobs(
        keywords="fraud",
        sources=[],
        ats_targets=[
            {
                "provider": "greenhouse",
                "identifier": "example-bank",
                "company": "Example Bank",
            }
        ],
    )

    assert result == []
    assert broad_called is False
    assert ats_called is False


@pytest.mark.asyncio
async def test_default_sources_are_used_only_when_sources_are_omitted(monkeypatch):
    received_sources = None

    async def fake_broad(**kwargs):
        nonlocal received_sources
        received_sources = kwargs["sources"]
        return [
            {
                "external_id": "jobbank:1",
                "title": "Fraud Analyst",
                "company": "Example Bank",
                "url": "https://example.test/job/1",
                "source": "jobbank",
            }
        ]

    monkeypatch.setattr(discovery_search, "search_broad_jobs", fake_broad)

    result = await discovery_search.search_jobs(keywords="fraud", sources=None)

    assert received_sources == ["indeed", "linkedin", "jobbank"]
    assert len(result) == 1
    assert result[0]["raw_data"]["official_public_ats"] is False


@pytest.mark.asyncio
async def test_official_targets_run_only_for_selected_provider(monkeypatch):
    called_targets = []

    async def fake_ats(target, **kwargs):
        called_targets.append(target)
        return [
            {
                "external_id": f"{target['provider']}:{target['identifier']}:1",
                "title": "Fraud Investigator",
                "company": target["company"],
                "url": f"https://example.test/{target['provider']}/1",
                "source": target["provider"],
                "raw_data": {"official_public_ats": True},
            }
        ]

    monkeypatch.setattr(discovery_search, "discover_public_ats_target", fake_ats)

    result = await discovery_search.search_jobs(
        keywords="fraud",
        sources=["greenhouse"],
        ats_targets=[
            {
                "provider": "greenhouse",
                "identifier": "example-bank",
                "company": "Example Bank",
            },
            {
                "provider": "lever",
                "identifier": "example-fintech",
                "company": "Example Fintech",
            },
        ],
    )

    assert called_targets == [
        {
            "provider": "greenhouse",
            "identifier": "example-bank",
            "company": "Example Bank",
        }
    ]
    assert len(result) == 1
    assert result[0]["source"] == "greenhouse"
