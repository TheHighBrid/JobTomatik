from pathlib import Path


def test_verifier_binds_native_runtime():
    verifier = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'payload.get("runtime") != "android_native_chrome_cdp"' in verifier
