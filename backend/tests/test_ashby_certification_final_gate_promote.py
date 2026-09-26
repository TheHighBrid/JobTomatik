from pathlib import Path


def test_promotion_follows_validated_physical_proof():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Only after the physical evidence passes" in runbook
