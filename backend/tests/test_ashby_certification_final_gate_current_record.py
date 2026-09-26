from pathlib import Path


def test_physical_gate_records_evidence_at_canonical_path():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "evidence/ashby-real-certification.json" in runbook
