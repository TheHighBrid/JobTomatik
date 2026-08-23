import pytest

from app.services.ats_ashby import AshbyAdapter


POSTING_ID = "7458d4e9-da2e-47bd-98cb-adfda43d42b2"


class FakeFrame:
    def __init__(self, url, selectors=None):
        self.url = url
        self._selectors = set(selectors or [])

    async def query_selector(self, selector):
        return object() if selector in self._selectors else None


class FakePage:
    def __init__(self, frames):
        self.main_frame = FakeFrame("https://careers.example.test/job")
        self.frames = [self.main_frame, *frames]

    async def query_selector(self, selector):
        return None


class FakeControl:
    def __init__(self):
        self.clicks = 0

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    async def click(self):
        self.clicks += 1


class FakePrepareSurface:
    def __init__(self, url, control=None):
        self.url = url
        self.control = control
        self.queries = []
        self.waits = []

    async def query_selector(self, selector):
        self.queries.append(selector)
        if self.control is not None and selector == 'a[href*="/application"]':
            return self.control
        return None

    async def wait_for_load_state(self, state, timeout=None):
        self.waits.append((state, timeout))

    async def wait_for_timeout(self, timeout):
        self.waits.append(("timeout", timeout))


@pytest.mark.asyncio
async def test_resolve_surface_prefers_application_frame_over_other_ashby_frames():
    decoration = FakeFrame(
        "https://jobs.ashbyhq.com/ashby/embed",
        selectors={'input:not([type="hidden"])'},
    )
    application = FakeFrame(
        f"https://jobs.ashbyhq.com/ashby/{POSTING_ID}/application?embed=true",
        selectors={'form[action*="ashbyhq.com" i]'},
    )
    page = FakePage([decoration, application])

    resolved = await AshbyAdapter().resolve_surface(page)

    assert resolved is application


@pytest.mark.asyncio
async def test_prepare_recognizes_query_suffixed_application_url_without_clicking():
    surface = FakePrepareSurface(
        f"https://jobs.ashbyhq.com/ashby/{POSTING_ID}/application?utm_source=embedded"
    )
    log = []

    await AshbyAdapter().prepare(surface, log)

    assert surface.queries == []
    assert log == []


@pytest.mark.asyncio
async def test_prepare_reveals_query_suffixed_application_link():
    control = FakeControl()
    surface = FakePrepareSurface(
        f"https://jobs.ashbyhq.com/ashby/{POSTING_ID}",
        control=control,
    )
    log = []

    await AshbyAdapter().prepare(surface, log)

    assert control.clicks == 1
    assert log == [{
        "action": "ashby_application_revealed",
        "selector": 'a[href*="/application"]',
    }]
