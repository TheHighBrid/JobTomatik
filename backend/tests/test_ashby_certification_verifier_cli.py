from pathlib import Path


def test_verifier_accepts_evidence_path():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert 'parser.add_argument("evidence", type=Path)' in source
