from pathlib import Path


def test_physical_gate_rejects_ambiguous_evidence():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "evidence is invalid if confirmation is ambiguous" in runbook
