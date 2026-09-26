from pathlib import Path


def test_physical_proof_uses_real_intended_job():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "real Ashby-hosted role" in runbook
    assert "genuinely intends to apply to" in runbook
