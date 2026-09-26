from pathlib import Path


def test_current_android_runtime_is_authoritative():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "current Android/native-Chrome runtime" in contract
