from pathlib import Path


CONTRACT = Path(__file__).resolve().parents[1] / "app/services/application_browser_contract.py"


def test_native_discovery_recovery_is_bounded():
    source = CONTRACT.read_text()
    function = "async def read_native_identity" + source.split(
        "async def read_native_identity", 1
    )[1].split("\n\ndef ", 1)[0]
    assert "range(3)" in function
    assert "0.35 * (attempt + 1)" in function
