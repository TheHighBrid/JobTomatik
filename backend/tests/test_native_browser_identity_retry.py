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

    async def fake_get(self, url):
        nonlocal calls
        calls += 1
        if calls == 1:
            request = httpx.Request("GET", url)
            raise httpx.ReadTimeout("transient", request=request)
        return httpx.Response(200, json=IDENTITY, request=httpx.Request("GET", url))

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", fake_sleep)

    result = await read_native_identity("http://127.0.0.1:9223")

    assert calls == 2
    assert sleeps == [0.35]
    assert result["Android-Package"] == "com.android.chrome"
    assert result["Browser"] == IDENTITY["Browser"]


@pytest.mark.asyncio
async def test_native_identity_still_fails_closed_after_retry_budget(monkeypatch):
    calls = 0
    sleeps: list[float] = []

    async def fake_get(self, url):
        nonlocal calls
        calls += 1
        request = httpx.Request("GET", url)
        raise httpx.ReadTimeout("persistent", request=request)

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", fake_sleep)

    with pytest.raises(BrowserContractError, match="after transient retries"):
        await read_native_identity("http://127.0.0.1:9223")

    assert calls == 3
    assert sleeps == [0.35, 0.7]


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.com:9223",
        "http://127.0.0.1:9223/path",
        "https://127.0.0.1:9223",
    ],
)
async def test_native_identity_rejects_non_loopback_or_non_contract_endpoints_before_io(
    monkeypatch, endpoint
):
    async def unexpected_get(self, url):
        raise AssertionError(f"network IO must not run for invalid endpoint: {url}")

    monkeypatch.setattr(httpx.AsyncClient, "get", unexpected_get)

    with pytest.raises(BrowserContractError, match="ENDPOINT_INVALID"):
        await read_native_identity(endpoint)


@pytest.mark.asyncio
async def test_native_identity_uses_validated_loopback_port_and_proxy_free_client(monkeypatch):
    observed = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            observed["kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            observed["url"] = url
            return httpx.Response(200, json=IDENTITY, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    result = await read_native_identity("http://localhost:9223")

    timeout = observed["kwargs"]["timeout"]
    assert observed["url"] == "http://127.0.0.1:9223/json/version"
    assert observed["kwargs"]["trust_env"] is False
    assert observed["kwargs"]["follow_redirects"] is False
    assert timeout.connect == 2.0
    assert timeout.read == 5.0
    assert result["Android-Package"] == "com.android.chrome"


@pytest.mark.asyncio
async def test_native_identity_preserves_application_message_after_persistent_failure(monkeypatch):
    async def fake_get(self, url):
        request = httpx.Request("GET", url)
        raise httpx.ReadTimeout("persistent", request=request)

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    monkeypatch.setattr("app.services.application_browser_contract.asyncio.sleep", no_sleep)

    with pytest.raises(BrowserContractError) as exc_info:
        await read_native_identity("http://127.0.0.1:9223")

    message = str(exc_info.value)
    assert "preserve the application" in message
    assert "reconnect the selected Chrome transport" in message
