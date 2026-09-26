from pathlib import Path


def test_physical_proof_must_validate():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "The verifier must exit zero" in runbook
