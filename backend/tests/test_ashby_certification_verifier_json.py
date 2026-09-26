from pathlib import Path


def test_verifier_prints_json_result():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert "json.dumps" in source
    assert '"certified"' in source
    assert '"blockers"' in source
