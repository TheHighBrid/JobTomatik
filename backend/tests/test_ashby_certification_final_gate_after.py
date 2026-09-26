from pathlib import Path


def test_metadata_promotion_happens_only_after_physical_evidence():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Only after the physical evidence passes may Ashby adapter metadata" in runbook
