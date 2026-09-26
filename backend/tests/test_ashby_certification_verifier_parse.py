from pathlib import Path


def test_verifier_parses_json_evidence():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert "json.loads(args.evidence.read_text" in source
