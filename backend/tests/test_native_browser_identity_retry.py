import httpx
import pytest

from app.services.application_browser_contract import (
    BrowserContractError,
    read_native_identity,
)


IDENTITY = {
    "Android-Package": "com.android.chrome",
    "Browser": "Chrome/152.0.7977.82",
    "User-Agent": "Mozilla/5.0",
    "webSocketDebuggerUrl": "ws://127.0.0.1:9223/devtools/browser/12345678-1234-1234-1234-123456789abc",
}


@pytest.mark.asyncio
async def test_native_identity_recovers_after_transient_timeout(monkeypatch):
    calls = 0
    sleeps: list[float] = []

    async def fake_http(_endpoint):
        nonlocal calls
        calls += 1
        if calls == 1:
            request = httpx.Request("GET", "http://127.0.0.1:9223/json/version")
            raise httpx.ReadTimeout("transient", request=request)
        return IDENTITY

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.services.application_browser_contract._read_native_identity_http", fake_http)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", fake_sleep)

    result = await read_native_identity("http://127.0.0.1:9223")

    assert calls == 2
    assert sleeps == [0.2]
    assert result["Android-Package"] == "com.android.chrome"
    assert result["Browser"] == IDENTITY["Browser"]


@pytest.mark.asyncio
async def test_native_identity_falls_back_to_cdp_after_http_retry_budget(monkeypatch):
    calls = 0
    sleeps: list[float] = []

    async def fake_http(_endpoint):
        nonlocal calls
        calls += 1
        request = httpx.Request("GET", "http://127.0.0.1:9223/json/version")
        raise httpx.ReadTimeout("persistent-http-stall", request=request)

    async def fake_cdp(endpoint):
        assert endpoint == "http://127.0.0.1:9223"
        return IDENTITY

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("app.services.application_browser_contract._read_native_identity_http", fake_http)
    monkeypatch.setattr("app.services.application_browser_contract._read_native_identity_playwright", fake_cdp)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", fake_sleep)

    result = await read_native_identity("http://127.0.0.1:9223")

    assert calls == 5
    assert sleeps == [0.2, 0.4, 0.6000000000000001, 0.8]
    assert result["Android-Package"] == "com.android.chrome"


@pytest.mark.asyncio
async def test_native_identity_still_fails_closed_when_http_and_cdp_fail(monkeypatch):
    async def fake_http(_endpoint):
        request = httpx.Request("GET", "http://127.0.0.1:9223/json/version")
        raise httpx.ReadTimeout("persistent", request=request)

    async def fake_cdp(_endpoint):
        raise TimeoutError("cdp unavailable")

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr("app.services.application_browser_contract._read_native_identity_http", fake_http)
    monkeypatch.setattr("app.services.application_browser_contract._read_native_identity_playwright", fake_cdp)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", no_sleep)

    with pytest.raises(BrowserContractError, match="after transient retries"):
        await read_native_identity("http://127.0.0.1:9223")


@pytest.mark.asyncio
async def test_native_identity_mismatch_is_not_retried(monkeypatch):
    calls = 0

    async def fake_http(_endpoint):
        nonlocal calls
        calls += 1
        return {
            "Android-Package": "org.chromium.chrome",
            "Browser": "Chrome/152.0.7977.82",
            "User-Agent": "Mozilla/5.0",
            "webSocketDebuggerUrl": IDENTITY["webSocketDebuggerUrl"],
        }

    async def no_sleep(_delay):
        raise AssertionError("identity mismatch must fail closed without retry backoff")

    monkeypatch.setattr("app.services.application_browser_contract._read_native_identity_http", fake_http)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", no_sleep)

    with pytest.raises(BrowserContractError, match="IDENTITY_MISMATCH"):
        await read_native_identity("http://127.0.0.1:9223")

    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com:9223",
        "http://127.0.0.1:9223/path",
        "https://127.0.0.1:9223",
    ],
)
async def test_native_identity_rejects_non_loopback_or_non_contract_endpoints_before_io(monkeypatch, endpoint):
    async def unexpected_http(_endpoint):
        raise AssertionError(f"network IO must not run for invalid endpoint: {endpoint}")

    monkeypatch.setattr("app.services.application_browser_contract._read_native_identity_http", unexpected_http)

    with pytest.raises(BrowserContractError, match="ENDPOINT_INVALID"):
        await read_native_identity(endpoint)


@pytest.mark.asyncio
async def test_native_identity_preserves_application_message_after_persistent_failure(monkeypatch):
    async def fake_http(_endpoint):
        request = httpx.Request("GET", "http://127.0.0.1:9223/json/version")
        raise httpx.ReadTimeout("persistent", request=request)

    async def fake_cdp(_endpoint):
        raise TimeoutError("persistent")

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr("app.services.application_browser_contract._read_native_identity_http", fake_http)
    monkeypatch.setattr("app.services.application_browser_contract._read_native_identity_playwright", fake_cdp)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", no_sleep)

    with pytest.raises(BrowserContractError) as exc_info:
        await read_native_identity("http://127.0.0.1:9223")

    message = str(exc_info.value)
    assert "preserve the application" in message
    assert "reconnect the selected Chrome transport" in message
