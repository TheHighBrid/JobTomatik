from pathlib import Path


def test_physical_gate_validates_canonical_evidence():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "verify_ashby_real_certification.py evidence/ashby-real-certification.json" in runbook
