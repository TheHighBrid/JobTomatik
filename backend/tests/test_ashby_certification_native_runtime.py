from pathlib import Path


def test_certification_contract_names_native_runtime():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert '"android_native_chrome_cdp"' in verifier
    assert "Android/native-Chrome stack" in runbook
