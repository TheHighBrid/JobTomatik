from pathlib import Path


def test_final_evidence_verifier_is_machine_readable():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert '"certified": not blockers' in source
    assert '"blockers": blockers' in source
