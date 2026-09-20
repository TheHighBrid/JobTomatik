from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import application_browser_contract as contract_module
from app.services import browser_runtime
from app.services.application_browser_contract import (
    BrowserContractError,
    application_browser_contract,
    connect_native_browser,
    validate_native_identity,
)
from scripts import application_browser_contract as launcher_contract


ENDPOINT = "http://127.0.0.1:9223"
IDENTITY = {
    "Android-Package": "com.android.chrome",
    "Browser": "Chrome/152.0.7977.82",
    "User-Agent": "Mozilla/5.0 (Linux; Android 16) Chrome/152.0.7977.82",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/browser",
}


def settings(endpoint=ENDPOINT, provider="native_chrome"):
    return SimpleNamespace(application_browser_cdp_endpoint=endpoint, application_browser_provider=provider)


@pytest.mark.parametrize("provider", ["auto", "native_chrome"])
def test_managed_worker_requires_endpoint(monkeypatch, provider):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    with pytest.raises(BrowserContractError, match="ENDPOINT_REQUIRED"):
        application_browser_contract(settings("", provider))


@pytest.mark.parametrize("provider", ["local", "external_cdp"])
def test_managed_worker_cannot_select_alternate_provider(monkeypatch, provider):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    with pytest.raises(BrowserContractError, match="NATIVE_CHROME_REQUIRED"):
        application_browser_contract(settings(ENDPOINT, provider))


def test_desktop_auto_keeps_local_and_external_support(monkeypatch):
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_MODE", raising=False)
    assert application_browser_contract(settings("", "auto")).provider == "local"
    assert application_browser_contract(settings(ENDPOINT, "auto")).provider == "external_cdp"


@pytest.mark.parametrize("endpoint", ["http://example.com:9223", "http://127.0.0.1", "http://127.0.0.1:abc", "http://u:p@localhost:9223", "http://localhost:9223/other", "http://localhost:9223?token=x"])
def test_native_endpoint_must_be_explicit_local_forward(endpoint):
    with pytest.raises(BrowserContractError):
        application_browser_contract(settings(endpoint))


@pytest.mark.parametrize("separators", [(": ", ", "), (":", ",")])
def test_native_identity_is_independent_of_json_whitespace(separators):
    colon, comma = separators
    payload = json.loads(json.dumps(IDENTITY, separators=(comma, colon)))
    assert validate_native_identity(payload, ENDPOINT) == IDENTITY


@pytest.mark.parametrize("payload", [[], {}, {**IDENTITY, "Android-Package": "org.chromium.chrome"}, {**IDENTITY, "webSocketDebuggerUrl": "ws://example.com:9223/devtools/browser"}, {**IDENTITY, "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser"}])
def test_native_identity_rejects_wrong_package_or_socket(payload):
    with pytest.raises(BrowserContractError):
        validate_native_identity(payload, ENDPOINT)


@pytest.mark.asyncio
async def test_unavailable_native_identity_has_no_browser_fallback(monkeypatch):
    async def unavailable(request):
        raise httpx.ConnectError("offline", request=request)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(contract_module.httpx, "AsyncClient", lambda **kwargs: client_type(transport=httpx.MockTransport(unavailable), **kwargs))
    with pytest.raises(BrowserContractError, match="NATIVE_CHROME_UNAVAILABLE"):
        await contract_module.read_native_identity(ENDPOINT)


def connected_browser():
    session = SimpleNamespace(send=AsyncMock(return_value={"product": IDENTITY["Browser"], "userAgent": IDENTITY["User-Agent"]}), detach=AsyncMock())
    browser = SimpleNamespace(new_browser_cdp_session=AsyncMock(return_value=session), contexts=[SimpleNamespace(pages=[], new_page=AsyncMock())])
    return browser, session


@pytest.mark.asyncio
async def test_attachment_pins_websocket_and_verifies_actual_connection(monkeypatch):
    monkeypatch.setattr(contract_module, "read_native_identity", AsyncMock(side_effect=[IDENTITY, IDENTITY]))
    browser, session = connected_browser()
    connect = AsyncMock(return_value=browser)
    result = await connect_native_browser(None, application_browser_contract(settings()), connect)
    connect.assert_awaited_once_with(None, IDENTITY["webSocketDebuggerUrl"])
    session.send.assert_awaited_once_with("Browser.getVersion")
    session.detach.assert_awaited_once()
    assert result._jobtomatik_application_browser_identity["connection_identity_verified"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["changed_http", "changed_connection", "disconnect", "multiple_contexts"])
async def test_attachment_changes_reject_before_creating_application_page(monkeypatch, failure):
    browser, session = connected_browser()
    after = IDENTITY
    if failure == "changed_http":
        after = {**IDENTITY, "Browser": "Chrome/153"}
    elif failure == "changed_connection":
        session.send.return_value = {"product": "Chrome/149", "userAgent": "Linux desktop"}
    elif failure == "disconnect":
        after = BrowserContractError("ANDROID_NATIVE_CHROME_UNAVAILABLE")
    else:
        browser.contexts.append(SimpleNamespace(pages=[]))
    monkeypatch.setattr(contract_module, "read_native_identity", AsyncMock(side_effect=[IDENTITY, after]))
    with pytest.raises(BrowserContractError):
        await connect_native_browser(None, application_browser_contract(settings()), AsyncMock(return_value=browser))
    browser.contexts[0].new_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_never_locally_launches_when_native_endpoint_is_missing(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.setattr(browser_runtime, "get_settings", lambda: settings("", "auto"))
    launch = AsyncMock()
    monkeypatch.setattr(browser_runtime._base, "launch_retainable_browser", launch)
    with pytest.raises(BrowserContractError, match="ENDPOINT_REQUIRED"):
        await browser_runtime.launch_application_browser(None)
    launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_wrong_browser_rejects_before_tab_or_local_launch(monkeypatch):
    monkeypatch.setattr(browser_runtime, "get_settings", settings)
    read = AsyncMock(side_effect=BrowserContractError("ANDROID_NATIVE_CHROME_IDENTITY_MISMATCH"))
    monkeypatch.setattr(contract_module, "read_native_identity", read)
    connect = AsyncMock()
    monkeypatch.setattr(browser_runtime, "_connect_external_playwright_over_cdp", connect)
    with pytest.raises(browser_runtime.BrowserRuntimeError, match="IDENTITY_MISMATCH"):
        await browser_runtime.launch_application_browser(None)
    connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_retained_handoff_cannot_reconnect_to_different_endpoint(monkeypatch):
    monkeypatch.setattr(browser_runtime, "get_settings", settings)
    connect = AsyncMock()
    monkeypatch.setattr(browser_runtime, "_connect_external_playwright_over_cdp", connect)
    with pytest.raises(browser_runtime.BrowserRuntimeError, match="ENDPOINT_MISMATCH"):
        await browser_runtime.connect_retained_application_browser(None, "http://127.0.0.1:9222")
    connect.assert_not_awaited()


def test_launcher_preserves_existing_endpoint_and_ignores_caller_overrides(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("APPLICATION_BROWSER_CDP_ENDPOINT=http://127.0.0.1:9333\n")
    monkeypatch.setattr(launcher_contract, "BACKEND_ROOT", tmp_path)
    monkeypatch.setenv("APPLICATION_BROWSER_CDP_ENDPOINT", "http://127.0.0.1:9222")
    monkeypatch.setenv("APPLICATION_BROWSER_PROVIDER", "external_cdp")
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    contract = launcher_contract.managed_browser_contract()
    assert contract.endpoint == "http://127.0.0.1:9333"
    assert contract.provider == "native_chrome"


def test_launcher_initializes_new_endpoint_without_changing_config(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher_contract, "BACKEND_ROOT", tmp_path)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    assert launcher_contract.managed_browser_contract().endpoint == ENDPOINT
    assert not (tmp_path / ".env").exists()
