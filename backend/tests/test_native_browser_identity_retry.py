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
async def test_native_identity_recovers_after_transient_timeout(monkeypatch):
    calls = 0

    async def fake_get(self, url):
        nonlocal calls
        calls += 1
        if calls == 1:
            request = httpx.Request("GET", url)
            raise httpx.ReadTimeout("transient", request=request)
        return httpx.Response(200, json=IDENTITY, request=httpx.Request("GET", url))

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", no_sleep)

    result = await read_native_identity("http://127.0.0.1:9223")

    assert calls == 2
    assert result["Android-Package"] == "com.android.chrome"
    assert result["Browser"] == IDENTITY["Browser"]


@pytest.mark.asyncio
async def test_native_identity_still_fails_closed_after_retry_budget(monkeypatch):
    calls = 0

    async def fake_get(self, url):
        nonlocal calls
        calls += 1
        request = httpx.Request("GET", url)
        raise httpx.ReadTimeout("persistent", request=request)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", no_sleep)

    with pytest.raises(BrowserContractError, match="after transient retries"):
        await read_native_identity("http://127.0.0.1:9223")

    assert calls == 3


@pytest.mark.asyncio
async def test_native_identity_mismatch_is_not_retried(monkeypatch):
    calls = 0

    async def fake_get(self, url):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "Android-Package": "org.chromium.chrome",
                "Browser": "Chrome/152.0.7977.82",
                "User-Agent": "Mozilla/5.0",
                "webSocketDebuggerUrl": IDENTITY["webSocketDebuggerUrl"],
            },
            request=httpx.Request("GET", url),
        )

    async def no_sleep(_delay):
        raise AssertionError("identity mismatch must fail closed without retry backoff")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", no_sleep)

    with pytest.raises(BrowserContractError, match="IDENTITY_MISMATCH"):
        await read_native_identity("http://127.0.0.1:9223")

    assert calls == 1
