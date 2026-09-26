from pathlib import Path


def test_real_gate_requires_applied_reconciliation():
    text = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert "reconcile the JobTomatik application to `applied` only after sufficient evidence" in text
