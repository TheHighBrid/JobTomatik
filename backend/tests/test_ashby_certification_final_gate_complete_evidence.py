from pathlib import Path


def test_completion_evidence_precedes_status_transition():
    contract = Path("docs/ASHBY_REAL_CERTIFICATION.md").read_text(encoding="utf-8")
    assert contract.index("## Completion evidence") < contract.index("Only then")
