from pathlib import Path


def test_verifier_emits_machine_readable_certified_and_blockers_fields():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    assert '"certified": not blockers' in source
    assert '"blockers": blockers' in source
    assert "return 1 if blockers else 0" in source
