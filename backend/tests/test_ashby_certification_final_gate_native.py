from pathlib import Path


def test_physical_proof_uses_android_native_chrome():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Android/native-Chrome stack" in runbook
