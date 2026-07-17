import pytest

from scripts import certify_greenhouse_live


def test_resolve_greenhouse_job_target_recovers_job_id_from_requested_url():
    assert certify_greenhouse_live.resolve_greenhouse_job_target(
        "https://job-boards.greenhouse.io/acme?error=true",
        "https://job-boards.greenhouse.io/acme?error=true",
        "https://boards.greenhouse.io/acme/jobs/7654321",
    ) == ("acme", "7654321")


@pytest.mark.asyncio
async def test_inspect_live_url_uses_requested_url_for_schema_fallback(monkeypatch):
    class FakeLocator:
        async def evaluate_all(self, _script):
            return 0

    class FakeSurface:
        url = "https://job-boards.greenhouse.io/acme?error=true"

        def locator(self, _selector):
            return FakeLocator()

    class FakePage:
        def __init__(self):
            self.url = ""

        async def goto(self, _url, **_kwargs):
            self.url = "https://job-boards.greenhouse.io/acme?error=true"

        async def wait_for_load_state(self, *_args, **_kwargs):
            return None

        async def title(self):
            return "Page not found"

        async def close(self):
            return None

    class FakeBrowser:
        async def new_page(self):
            return FakePage()

    class FakeAdapter:
        name = "greenhouse"
        version = "1.1.0"

        async def resolve_surface(self, _page):
            return FakeSurface()

        async def prepare(self, _surface, _log):
            return None

        async def find_next_button(self, _surface):
            return None

        async def find_submit_button(self, _surface):
            return None

    async def fake_detect_ats_adapter(_page, _url):
        return FakeAdapter()

    async def fake_fetch_greenhouse_job_schema(board_token, job_id):
        assert (board_token, job_id) == ("acme", "7654321")
        return {"id": 7654321, "title": "Analyst", "questions": []}

    monkeypatch.setattr(
        certify_greenhouse_live,
        "detect_ats_adapter",
        fake_detect_ats_adapter,
    )
    monkeypatch.setattr(
        certify_greenhouse_live,
        "fetch_greenhouse_job_schema",
        fake_fetch_greenhouse_job_schema,
    )

    report = await certify_greenhouse_live.inspect_live_url(
        "https://boards.greenhouse.io/acme/jobs/7654321",
        FakeBrowser(),
    )

    assert report["board_token"] == "acme"
    assert report["job_id"] == "7654321"
    assert report["schema"]["job_id"] == 7654321
