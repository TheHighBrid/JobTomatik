from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import application_browser_contract as contract_module
from app.services.application_browser_contract import (
    application_browser_contract,
    connect_native_browser,
)


ENDPOINT = "http://127.0.0.1:9223"
WS_ENDPOINT = "ws://127.0.0.1:9223/devtools/browser"
IDENTITY = {
    "Android-Package": "com.android.chrome",
    "Browser": "Chrome/153.0.8010.52",
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
    ),
    "webSocketDebuggerUrl": WS_ENDPOINT,
}


def settings():
    return SimpleNamespace(
        application_browser_cdp_endpoint=ENDPOINT,
        application_browser_provider="native_chrome",
    )


def connected_browser():
    session = SimpleNamespace(
        send=AsyncMock(
            return_value={
                "product": IDENTITY["Browser"],
                "userAgent": IDENTITY["User-Agent"],
            }
        ),
        detach=AsyncMock(),
    )
    browser = SimpleNamespace(
        new_browser_cdp_session=AsyncMock(return_value=session),
        contexts=[SimpleNamespace(pages=[])],
    )
    return browser, session


@pytest.mark.asyncio
async def test_recent_validated_identity_recovers_transient_http_discovery_stall(
    monkeypatch,
    tmp_path,
):
    cache_path = tmp_path / "native-chrome-identity.json"
    monkeypatch.setenv(
        "JOBTOMATIK_NATIVE_CHROME_IDENTITY_CACHE",
        str(cache_path),
    )

    async def ready(request):
        return httpx.Response(200, json=IDENTITY, request=request)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        contract_module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(ready),
            **kwargs,
        ),
    )

    fresh = await contract_module.read_native_identity(ENDPOINT)
    assert fresh == IDENTITY
    assert cache_path.exists()

    async def stalled(request):
        raise httpx.ReadTimeout("discovery stalled", request=request)

    monkeypatch.setattr(
        contract_module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(stalled),
            **kwargs,
        ),
    )
    monkeypatch.setattr(contract_module.asyncio, "sleep", AsyncMock())

    recovered = await contract_module.read_native_identity(ENDPOINT)

    assert recovered["Android-Package"] == "com.android.chrome"
    assert recovered["Browser"] == IDENTITY["Browser"]
    assert recovered["webSocketDebuggerUrl"] == WS_ENDPOINT
    assert recovered[contract_module._NATIVE_IDENTITY_CACHE_SOURCE_KEY] == (
        contract_module._NATIVE_IDENTITY_CACHE_SOURCE_VALUE
    )


@pytest.mark.asyncio
async def test_cached_identity_attaches_directly_to_validated_websocket(monkeypatch):
    cached = {
        **IDENTITY,
        contract_module._NATIVE_IDENTITY_CACHE_SOURCE_KEY: (
            contract_module._NATIVE_IDENTITY_CACHE_SOURCE_VALUE
        ),
    }
    read_identity = AsyncMock(return_value=cached)
    monkeypatch.setattr(contract_module, "read_native_identity", read_identity)

    browser, session = connected_browser()
    connect = AsyncMock(return_value=browser)

    result = await connect_native_browser(
        None,
        application_browser_contract(settings()),
        connect,
    )

    read_identity.assert_awaited_once_with(ENDPOINT)
    connect.assert_awaited_once_with(None, WS_ENDPOINT)
    session.send.assert_awaited_once_with("Browser.getVersion")
    session.detach.assert_awaited_once()
    assert result._jobtomatik_application_browser_identity[
        "connection_identity_verified"
    ] is True
    assert result._jobtomatik_application_browser_identity["identity_source"] == (
        contract_module._NATIVE_IDENTITY_CACHE_SOURCE_VALUE
    )


@pytest.mark.asyncio
async def test_invalid_cached_identity_never_bypasses_native_package_check(
    monkeypatch,
    tmp_path,
):
    cache_path = tmp_path / "native-chrome-identity.json"
    monkeypatch.setenv(
        "JOBTOMATIK_NATIVE_CHROME_IDENTITY_CACHE",
        str(cache_path),
    )
    cache_path.write_text(
        json.dumps(
            {
                "endpoint": ENDPOINT,
                "cached_at": contract_module.time.time(),
                "identity": {
                    **IDENTITY,
                    "Android-Package": "org.chromium.chrome",
                },
            }
        ),
        encoding="utf-8",
    )

    async def stalled(request):
        raise httpx.ReadTimeout("discovery stalled", request=request)

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        contract_module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(stalled),
            **kwargs,
        ),
    )
    monkeypatch.setattr(contract_module.asyncio, "sleep", AsyncMock())

    with pytest.raises(
        contract_module.BrowserContractError,
        match="ANDROID_NATIVE_CHROME_UNAVAILABLE",
    ):
        await contract_module.read_native_identity(ENDPOINT)
