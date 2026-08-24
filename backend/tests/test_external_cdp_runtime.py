from types import SimpleNamespace

import pytest
from playwright import async_api as playwright_api

from app.services import browser_runtime
from app.services.browser_runtime_base import BrowserRuntimeError


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


class _UrlPage:
    def __init__(self, url):
        self.url = url


@pytest.mark.asyncio
async def test_external_cdp_attachment_rejects_ambiguous_multi_page_context():
    browser = type(
        "Browser",
        (),
        {"contexts": [type("Context", (), {"pages": [_UrlPage("https://one.test"), _UrlPage("https://two.test")]})()]},
    )()

    with pytest.raises(BrowserRuntimeError, match="multiple pages"):
        await browser_runtime._select_context_page(
            browser,
            viewport=None,
            resize_viewport=False,
        )


@pytest.mark.asyncio
async def test_launcher_attachment_probe_accepts_ambiguous_multi_page_context(
    monkeypatch,
):
    browser = type(
        "Browser",
        (),
        {
            "contexts": [
                type(
                    "Context",
                    (),
                    {"pages": [_UrlPage("https://one.test"), _UrlPage("https://two.test")]},
                )()
            ]
        },
    )()

    class FakePlaywrightManager:
        async def __aenter__(self):
            return SimpleNamespace(chromium=object())

        async def __aexit__(self, *_args):
            return None

    async def fake_wait(_endpoint):
        return None

    async def fake_connect(_playwright, _endpoint):
        return browser

    monkeypatch.setattr(playwright_api, "async_playwright", FakePlaywrightManager)
    monkeypatch.setattr(browser_runtime, "_wait_for_external_cdp_endpoint", fake_wait)
    monkeypatch.setattr(browser_runtime, "_connect_external_playwright_over_cdp", fake_connect)

    proof = await browser_runtime.probe_external_playwright_cdp_attachment(
        "http://127.0.0.1:9222"
    )

    assert proof["playwright_attach_ready"] is True
    assert proof["context_count"] == 1


@pytest.mark.asyncio
async def test_external_cdp_attachment_keeps_single_controlled_page():
    page = _UrlPage("https://controlled.test")
    context = type("Context", (), {"pages": [page]})()
    browser = type("Browser", (), {"contexts": [context]})()

    selected_context, selected_page = await browser_runtime._select_context_page(
        browser,
        viewport=None,
        resize_viewport=False,
    )

    assert selected_context is context
    assert selected_page is page


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
