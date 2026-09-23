from pathlib import Path


CONTRACT = Path(__file__).resolve().parents[1] / "app/services/application_browser_contract.py"


def test_native_identity_discovery_has_bounded_retry_and_no_provider_fallback():
    source = CONTRACT.read_text()
    function = "async def read_native_identity" + source.split(
        "async def read_native_identity", 1
    )[1].split("\n\ndef ", 1)[0]

    assert "for attempt in range(3)" in function
    assert "httpx.Timeout(5.0, connect=2.0)" in function
    assert "await asyncio.sleep" in function
    assert "native Chrome discovery remained unavailable after transient retries" in function
    assert "chromium" not in function.lower()
