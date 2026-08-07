from types import SimpleNamespace

import pytest

from app.services import browser_runtime


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "Browser": "Chrome/149",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/test",
        }


class FakePage:
    url = "https://www.linkedin.com/feed/"


class FakeContext:
    def __init__(self):
        self.pages = [FakePage()]

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page


class FakeBrowser:
    def __init__(self):
        self.contexts = [FakeContext()]


class FakeChromium:
    def __init__(self):
        self.calls = []

    async def connect_over_cdp(self, endpoint, timeout):
        self.calls.append((endpoint, timeout))
        return FakeBrowser()


class FakePlaywright:
    def __init__(self):
        self.chromium = FakeChromium()


@pytest.mark.asyncio
async def test_attach_retainable_browser_reuses_external_cdp_without_owning_process(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HANDOFF_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(browser_runtime.httpx, "get", lambda *args, **kwargs: FakeResponse())
    playwright = FakePlaywright()

    runtime = await browser_runtime.attach_retainable_browser(
        playwright,
        cdp_endpoint="http://127.0.0.1:9222/",
    )

    assert runtime.cdp_endpoint == "http://127.0.0.1:9222"
    assert runtime.owns_process is False
    assert runtime.process.pid is None
    assert runtime.process.poll() is None
    assert runtime.page.url == "https://www.linkedin.com/feed/"
    assert playwright.chromium.calls

    session_dir = runtime.session_dir
    runtime.terminate(remove_profile=True)
    assert not session_dir.exists()


@pytest.mark.asyncio
async def test_launch_application_browser_prefers_configured_external_cdp(monkeypatch):
    settings = SimpleNamespace(
        application_browser_cdp_endpoint="http://127.0.0.1:9222",
        application_browser_profile_dir="unused",
        application_browser_headless=True,
        application_browser_executable="",
    )
    calls = []
    sentinel = object()

    async def fake_attach(playwright, *, cdp_endpoint, viewport=None):
        calls.append((playwright, cdp_endpoint, viewport))
        return sentinel

    monkeypatch.setattr(browser_runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(browser_runtime, "attach_retainable_browser", fake_attach)

    playwright = object()
    result = await browser_runtime.launch_application_browser(
        playwright,
        viewport={"width": 900, "height": 700},
    )

    assert result is sentinel
    assert calls == [
        (
            playwright,
            "http://127.0.0.1:9222",
            {"width": 900, "height": 700},
        )
    ]
