from pathlib import Path


CONTRACT = Path(__file__).resolve().parents[1] / "app/services/application_browser_contract.py"


def test_native_discovery_retry_remains_loopback_only_and_proxy_free():
    source = CONTRACT.read_text()
    function = "async def read_native_identity" + source.split(
        "async def read_native_identity", 1
    )[1].split("\n\ndef ", 1)[0]
    assert 'identity_endpoint = f"http://127.0.0.1:{native_port}"' in function
    assert "trust_env=False" in function
    assert "follow_redirects=False" in function
