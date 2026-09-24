import httpx
import pytest

from app.services.application_browser_contract import BrowserContractError, read_native_identity


IDENTITY = {
    "Android-Package": "com.android.chrome",
    "Browser": "Chrome/152.0.7977.82",
    "User-Agent": "Mozilla/5.0",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/browser/12345678-1234-1234-1234-123456789abc",
}


@pytest.mark.asyncio
async def test_native_identity_retries_http_without_nested_playwright_fallback(monkeypatch):
    calls = 0

    async def fake_http(_endpoint):
        nonlocal calls
        calls += 1
        request = httpx.Request("GET", "http://127.0.0.1:9223/json/version")
        raise httpx.ReadTimeout("persistent-http-stall", request=request)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr("app.services.application_browser_contract._read_native_identity_http", fake_http)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", no_sleep)

    with pytest.raises(BrowserContractError, match="after transient retries"):
        await read_native_identity("http://127.0.0.1:9223")

    assert calls == 5
