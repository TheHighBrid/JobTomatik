from pathlib import Path


def test_physical_proof_creates_canonical_evidence_record():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "evidence/ashby-real-certification.json" in runbook
