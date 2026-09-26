from pathlib import Path


def test_verifier_documents_fail_closed_purpose():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert "Fail-closed verifier for retained Ashby real-runtime certification evidence" in source
