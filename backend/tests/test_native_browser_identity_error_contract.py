from pathlib import Path


CONTRACT = Path(__file__).resolve().parents[1] / "app/services/application_browser_contract.py"


def test_persistent_discovery_failure_explicitly_preserves_application():
    source = CONTRACT.read_text()
    function = "async def read_native_identity" + source.split(
        "async def read_native_identity", 1
    )[1].split("\n\ndef ", 1)[0]
    assert "preserve the application" in function
    assert "reconnect the selected Chrome transport" in function
