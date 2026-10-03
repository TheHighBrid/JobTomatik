from types import SimpleNamespace

import pytest

from app.services import browser_runtime_base as runtime_base


class _FakeProcess:
    pid = 12345
    returncode = None

    def poll(self):
        return None

    def terminate(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        return None


@pytest.mark.asyncio
async def test_owned_browser_ignores_legacy_executable_override(monkeypatch, tmp_path):
    """A configured executable path must never select the process JobTomatik launches."""
    captured = {}
    process = _FakeProcess()
    browser = object()
    context = object()
    page = object()
    playwright = SimpleNamespace(
        chromium=SimpleNamespace(executable_path="/trusted/playwright/chromium")
    )

    def fake_popen(args, **kwargs):
        captured["args"] = list(args)
        captured["kwargs"] = kwargs
        return process

    async def fake_wait(*_args, **_kwargs):
        return None

    async def fake_connect(*_args, **_kwargs):
        return browser

    async def fake_select(*_args, **_kwargs):
        return context, page

    monkeypatch.setenv("HANDOFF_STORAGE_DIR", str(tmp_path / "handoffs"))
    monkeypatch.setattr(runtime_base, "_reserve_port", lambda: 34567)
    monkeypatch.setattr(runtime_base.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(runtime_base, "_wait_for_cdp_endpoint", fake_wait)
    monkeypatch.setattr(runtime_base, "_connect_playwright_over_cdp", fake_connect)
    monkeypatch.setattr(runtime_base, "_select_context_page", fake_select)

    result = await runtime_base.launch_retainable_browser(
        playwright,
        executable_path="/untrusted/configured/browser",
    )

    assert captured["args"][0] == "/trusted/playwright/chromium"
    assert "/untrusted/configured/browser" not in captured["args"]
    assert result.process is process
    assert result.browser is browser
