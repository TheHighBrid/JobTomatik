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
async def test_default_sources_are_observed_independently(monkeypatch):
    received_sources = []

    async def fake_broad(**kwargs):
        source = kwargs["sources"][0]
        received_sources.append(source)
        if source != "jobbank":
            return []
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

    observed = await discovery_search.search_jobs_with_diagnostics(
        keywords="fraud",
        sources=None,
    )

    assert received_sources == ["indeed", "linkedin", "jobbank"]
    assert len(observed["jobs"]) == 1
    assert observed["jobs"][0]["raw_data"]["official_public_ats"] is False
    diagnostics = {item["source"]: item for item in observed["source_diagnostics"]}
    assert diagnostics["indeed"]["status"] == "success"
    assert diagnostics["indeed"]["result_count"] == 0
    assert diagnostics["jobbank"]["result_count"] == 1


@pytest.mark.asyncio
async def test_source_exception_is_recorded_without_exception_text(monkeypatch):
    class SecretBearingError(RuntimeError):
        pass

    async def fake_broad(**kwargs):
        source = kwargs["sources"][0]
        if source == "linkedin":
            raise SecretBearingError("https://user:password@example.test/private-token")
        return []

    monkeypatch.setattr(discovery_search, "search_broad_jobs", fake_broad)

    observed = await discovery_search.search_jobs_with_diagnostics(
        keywords="fraud",
        sources=["linkedin", "jobbank"],
    )

    linkedin = next(item for item in observed["source_diagnostics"] if item["source"] == "linkedin")
    assert linkedin["status"] == "failed"
    assert linkedin["error_code"] == "secretbearingerror"
    assert "message" not in linkedin
    assert "password" not in str(linkedin)
    assert "private-token" not in str(linkedin)


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

    observed = await discovery_search.search_jobs_with_diagnostics(
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
    assert len(observed["jobs"]) == 1
    assert observed["jobs"][0]["source"] == "greenhouse"
    assert observed["source_diagnostics"] == [
        {
            "source": "greenhouse",
            "kind": "public_ats",
            "status": "success",
            "result_count": 1,
            "target": "example-bank",
            "error_code": None,
        }
    ]


@pytest.mark.asyncio
async def test_explicit_public_ats_results_survive_broad_board_global_limit(monkeypatch):
    """Broad-board volume must not evict an explicitly configured public ATS path."""

    async def fake_broad(**kwargs):
        source = kwargs["sources"][0]
        return [
            {
                "external_id": f"{source}:{index}",
                "title": f"Broad role {index}",
                "company": "Broad Co",
                "url": f"https://example.test/{source}/{index}",
                "source": source,
            }
            for index in range(50)
        ]

    async def fake_ats(target, **kwargs):
        return [
            {
                "external_id": f"lever:{target['identifier']}:eligible",
                "title": "Eligible Risk Analyst",
                "company": target["company"],
                "url": "https://jobs.lever.co/example-bank/eligible",
                "source": "lever",
                "raw_data": {
                    "official_public_ats": True,
                    "ats_identifier": target["identifier"],
                },
            }
        ]

    monkeypatch.setattr(discovery_search, "search_broad_jobs", fake_broad)
    monkeypatch.setattr(discovery_search, "discover_public_ats_target", fake_ats)

    observed = await discovery_search.search_jobs_with_diagnostics(
        keywords="risk analyst",
        location="Ottawa, ON",
        sources=["jobbank", "linkedin", "indeed", "lever"],
        ats_targets=[
            {
                "provider": "lever",
                "identifier": "example-bank",
                "company": "Example Bank",
            }
        ],
        limit=50,
    )

    assert len(observed["jobs"]) == 50
    assert observed["jobs"][0]["external_id"] == "lever:example-bank:eligible"
    assert observed["jobs"][0]["raw_data"]["official_public_ats"] is True
    assert any(
        item["kind"] == "public_ats" and item["result_count"] == 1
        for item in observed["source_diagnostics"]
    )
