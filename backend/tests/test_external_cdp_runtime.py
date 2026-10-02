from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import browser_runtime
from app.services.browser_runtime_base import BrowserRuntimeError


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REFRESH_SCRIPT = BACKEND_ROOT / "scripts/refresh_android_jobtomatik_tabs.py"
CHECK_SCRIPT = BACKEND_ROOT / "scripts/check_android_browser_cdp.py"


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "Browser": "Chrome/149",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/test",
        }


class FakePage:
    def __init__(self, url="https://www.linkedin.com/feed/"):
        self.url = url
        self.viewport = None
        self.closed = False
        self.brought_to_front = 0
        self.bring_to_front_error = None

    async def set_viewport_size(self, viewport):
        self.viewport = viewport

    async def bring_to_front(self):
        self.brought_to_front += 1
        if self.bring_to_front_error is not None:
            raise self.bring_to_front_error

    def is_closed(self):
        return self.closed

    async def close(self, run_before_unload=False):
        self.closed = True


class FakeCDPSession:
    def __init__(self, target_id):
        self.target_id = target_id
        self.detached = False

    async def send(self, method):
        assert method == "Target.getTargetInfo"
        return {"targetInfo": {"targetId": self.target_id}}

    async def detach(self):
        self.detached = True


class FakeContext:
    def __init__(self, pages=None):
        self.pages = list(pages or [FakePage()])
        self.created_pages = []
        self.cdp_sessions = []

    async def new_page(self):
        page = FakePage("about:blank")
        self.pages.append(page)
        self.created_pages.append(page)
        return page

    async def new_cdp_session(self, page):
        session = FakeCDPSession(f"target-{self.pages.index(page)}")
        self.cdp_sessions.append(session)
        return session


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
    assert runtime.page.brought_to_front == 1
    assert first.url == "https://www.linkedin.com/feed/"
    assert second.url == "http://localhost:3000/applications/220"
    assert len(context.pages) == 3


@pytest.mark.asyncio
async def test_application_attachment_fails_closed_when_controlled_page_cannot_be_activated(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HANDOFF_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(browser_runtime, "_wait_for_external_cdp_endpoint", _noop_wait)
    context = FakeContext([FakePage("https://www.linkedin.com/feed/")])
    browser = FakeBrowser([context])
    playwright = FakePlaywright(browser)

    original_new_page = context.new_page

    async def new_page_with_activation_failure():
        page = await original_new_page()
        page.bring_to_front_error = RuntimeError("target activation failed")
        return page

    context.new_page = new_page_with_activation_failure

    with pytest.raises(
        BrowserRuntimeError,
        match="APPLICATION_BROWSER_CONTROLLED_PAGE_NOT_VISIBLE",
    ):
        await browser_runtime.attach_retainable_browser(
            playwright,
            cdp_endpoint="http://127.0.0.1:9222",
            create_controlled_page=True,
        )

    assert len(context.created_pages) == 1
    assert context.created_pages[0].brought_to_front == 1
    assert context.created_pages[0].closed is True


@pytest.mark.asyncio
async def test_controlled_page_target_id_uses_durable_chromium_target_identity():
    first = FakePage("https://www.linkedin.com/feed/")
    controlled = FakePage("https://boards.greenhouse.io/example")
    context = FakeContext([first, controlled])
    first.context = context
    controlled.context = context

    target_id = await browser_runtime.controlled_page_target_id(controlled)

    assert target_id == "target-1"
    assert context.cdp_sessions
    assert context.cdp_sessions[0].detached is True


@pytest.mark.asyncio
async def test_release_application_browser_closes_only_owned_controlled_page(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HANDOFF_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(browser_runtime, "_wait_for_external_cdp_endpoint", _noop_wait)
    monkeypatch.setattr(browser_runtime.httpx, "get", lambda *args, **kwargs: FakeResponse())
    first = FakePage("https://www.linkedin.com/feed/")
    second = FakePage("http://localhost:3000/applications/220")
    context = FakeContext([first, second])
    browser = FakeBrowser([context])
    runtime = await browser_runtime.attach_retainable_browser(
        FakePlaywright(browser),
        cdp_endpoint="http://127.0.0.1:9222",
        create_controlled_page=True,
    )
    controlled = runtime.page

    await browser_runtime.release_application_browser(runtime)

    assert controlled.closed is True
    assert first.closed is False
    assert second.closed is False
    assert runtime.process.poll() is None


@pytest.mark.asyncio
async def test_release_application_browser_retains_controlled_page_for_handoff(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("HANDOFF_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(browser_runtime, "_wait_for_external_cdp_endpoint", _noop_wait)
    monkeypatch.setattr(browser_runtime.httpx, "get", lambda *args, **kwargs: FakeResponse())
    context = FakeContext([FakePage("https://www.linkedin.com/feed/")])
    browser = FakeBrowser([context])
    runtime = await browser_runtime.attach_retainable_browser(
        FakePlaywright(browser),
        cdp_endpoint="http://127.0.0.1:9222",
        create_controlled_page=True,
    )
    controlled = runtime.page

    await browser_runtime.release_application_browser(
        runtime,
        retain_controlled_page=True,
    )

    assert controlled.closed is False
    assert runtime.process.poll() is None


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


def test_human_boundary_preserves_controlled_page_before_handoff_identity_persistence():
    form_source = (
        BACKEND_ROOT / "app" / "services" / "form_filler_handoff.py"
    ).read_text(encoding="utf-8")
    form_block = form_source.split("if _resumable_boundary(result):", 1)[1].split(
        "finally:", 1
    )[0]
    assert form_block.index("retained = True") < form_block.index(
        "retainable_application_browser_identity("
    )

    resolver_source = (
        BACKEND_ROOT / "app" / "services" / "application_target_resolver.py"
    ).read_text(encoding="utf-8")
    resolver_block = resolver_source.split(
        "if challenge and reason_code in _RESUMABLE_TARGET_REASONS:", 1
    )[1].split("return result", 1)[0]
    assert resolver_block.index("retained = True") < resolver_block.index(
        "retainable_application_browser_identity("
    )

@pytest.mark.asyncio
async def test_controlled_page_creation_recovers_android_target_create_refusal(monkeypatch):
    seed = FakePage("https://www.linkedin.com/feed/")
    recovered = FakePage("about:blank")

    class RecoverySession:
        detached = False

        async def send(self, method, params=None):
            assert method == "Runtime.evaluate"
            assert params["userGesture"] is True
            context.pages.append(recovered)
            return {"result": {}}

        async def detach(self):
            self.detached = True

    class RecoveryContext(FakeContext):
        async def new_page(self):
            raise RuntimeError("BrowserContext.new_page: Protocol error (Target.createTarget): Could not create a Tab")

        async def new_cdp_session(self, page):
            assert page is seed
            self.recovery_session = RecoverySession()
            return self.recovery_session

    context = RecoveryContext([seed])
    page = await browser_runtime._create_controlled_external_page(context)

    assert page is recovered
    assert context.pages == [seed, recovered]
    assert context.recovery_session.detached is True


@pytest.mark.asyncio
async def test_controlled_page_creation_does_not_mask_unrelated_new_page_failure():
    class BrokenContext(FakeContext):
        async def new_page(self):
            raise RuntimeError("permission denied")

    context = BrokenContext([FakePage()])
    with pytest.raises(RuntimeError, match="permission denied"):
        await browser_runtime._create_controlled_external_page(context)
