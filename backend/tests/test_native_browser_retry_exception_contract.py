from pathlib import Path


CONTRACT = Path(__file__).resolve().parents[1] / "app/services/application_browser_contract.py"


def test_native_retry_scope_does_not_swallow_identity_contract_errors():
    source = CONTRACT.read_text()
    function = "async def read_native_identity" + source.split(
        "async def read_native_identity", 1
    )[1].split("\n\ndef ", 1)[0]
    assert "except (httpx.HTTPError, ValueError)" in function
    assert "except Exception" not in function
