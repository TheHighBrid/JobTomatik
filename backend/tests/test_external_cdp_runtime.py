from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import browser_runtime
from app.services.browser_runtime_base import BrowserRuntimeError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REFRESH_SCRIPT = BACKEND_ROOT / "scripts/refresh_android_jobtomatik_tabs.py"
CHECK_SCRIPT = BACKEND_ROOT / "scripts/check_android_browser_cdp.py"


class FakePage:
    def __init__(self, url="https://www.linkedin.com/feed/"):
        self.url = url
        self.viewport = None

    async def set_viewport_size(self, viewport):
        self.viewport = viewport


class FakeContext:
    def __init__(self, pages=None):
        self.pages = list(pages or [FakePage()])
        self.created_pages = []

    async def new_page(self):
        page = FakePage("about:blank")
        self.pages.append(page)
        self.created_pages.append(page)
        return page


class FakeBrowser:
    def __init__(self, contexts=None):
        self.contexts = list(contexts or [FakeContext()])


class FakeChromium:
    def __init__(self, browser=None):
        self.calls = []
        self.browser = browser or FakeBrowser()

    async def connect_over_cdp(self, endpoint, timeout):
        self.calls.append((endpoint, timeout))
        return self.browser


class FakePlaywright:
    def __init__(self, browser=None):
        self.chromium = FakeChromium(browser)


async def _noop_wait(_endpoint):
    return None


@pytest.mark.asyncio
async def test_external_cdp_single_page_selector_remains_fail_closed_on_ambiguity():
    browser = FakeBrowser(
        [FakeContext([FakePage("https://one.test"), FakePage("https://two.test")])]
    )

    with pytest.raises(BrowserRuntimeError, match="multiple pages"):
        await browser_runtime._select_context_page(
            browser,
            viewport=None,
            resize_viewport=False,
        )


@pytest.mark.asyncio
async def test_external_cdp_attachment_keeps_single_controlled_existing_page():
    page = FakePage("https://controlled.test")
    context = FakeContext([page])
    browser = FakeBrowser([context])

    selected_context, selected_page = await browser_runtime._select_context_page(
        browser,
        viewport=None,
        resize_viewport=False,
    )

    assert selected_context is context
    assert selected_page is page


def test_external_browser_inventory_accepts_multiple_retained_pages():
    browser = FakeBrowser(
        [FakeContext([FakePage("https://one.test"), FakePage("https://two.test")])]
    )

    inventory = browser_runtime.external_browser_inventory(browser)

    assert inventory == {
        "context_count": 1,
        "page_count": 2,
        "current_url": "",
        "multiple_pages_present": True,
    }


@pytest.mark.asyncio
async def test_attach_retainable_browser_reuses_external_cdp_without_owning_process(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HANDOFF_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(browser_runtime, "_wait_for_external_cdp_endpoint", _noop_wait)
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
async def test_application_attachment_creates_new_controlled_page_when_browser_has_multiple_tabs(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HANDOFF_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(browser_runtime, "_wait_for_external_cdp_endpoint", _noop_wait)
    first = FakePage("https://www.linkedin.com/feed/")
    second = FakePage("http://localhost:3000/applications/220")
    context = FakeContext([first, second])
    browser = FakeBrowser([context])
    playwright = FakePlaywright(browser)

    runtime = await browser_runtime.attach_retainable_browser(
        playwright,
        cdp_endpoint="http://127.0.0.1:9222",
        viewport={"width": 900, "height": 700},
        create_controlled_page=True,
    )

    assert runtime.page is context.created_pages[0]
    assert runtime.page.url == "about:blank"
    assert runtime.page.viewport == {"width": 900, "height": 700}
    assert first.url == "https://www.linkedin.com/feed/"
    assert second.url == "http://localhost:3000/applications/220"
    assert len(context.pages) == 3


@pytest.mark.asyncio
async def test_application_attachment_rejects_multiple_browser_contexts(
    monkeypatch,
):
    monkeypatch.setattr(browser_runtime, "_wait_for_external_cdp_endpoint", _noop_wait)
    browser = FakeBrowser([FakeContext(), FakeContext()])
    playwright = FakePlaywright(browser)

    with pytest.raises(BrowserRuntimeError, match="multiple browser contexts"):
        await browser_runtime.attach_retainable_browser(
            playwright,
            cdp_endpoint="http://127.0.0.1:9222",
            create_controlled_page=True,
        )


@pytest.mark.asyncio
async def test_launch_application_browser_requests_fresh_controlled_external_page(monkeypatch):
    settings = SimpleNamespace(
        application_browser_cdp_endpoint="http://127.0.0.1:9222",
        application_browser_profile_dir="unused",
        application_browser_headless=True,
        application_browser_executable="",
    )
    calls = []
    sentinel = object()

    async def fake_attach(
        playwright,
        *,
        cdp_endpoint,
        viewport=None,
        create_controlled_page=False,
    ):
        calls.append(
            (playwright, cdp_endpoint, viewport, create_controlled_page)
        )
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
            True,
        )
    ]


def test_android_maintenance_scripts_do_not_require_single_application_tab():
    refresh_source = REFRESH_SCRIPT.read_text(encoding="utf-8")
    check_source = CHECK_SCRIPT.read_text(encoding="utf-8")

    assert "connect_external_playwright_browser" in refresh_source
    assert "launch_application_browser" not in refresh_source
    assert "probe_external_playwright_cdp" in check_source
    assert "launch_application_browser" not in check_source
