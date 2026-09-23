from pathlib import Path


CONTRACT = Path(__file__).resolve().parents[1] / "app/services/application_browser_contract.py"


def test_retry_does_not_weaken_native_identity_validation():
    source = CONTRACT.read_text()
    assert 'payload.get("Android-Package") != "com.android.chrome"' in source
    assert "ANDROID_NATIVE_CHROME_WEBSOCKET_MISMATCH" in source
    assert 'websocket.hostname in {"127.0.0.1", "localhost"}' in source
    assert 'return validate_native_identity(payload, identity_endpoint)' in source
