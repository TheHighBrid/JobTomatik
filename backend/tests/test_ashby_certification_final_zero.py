from pathlib import Path


def test_final_promotion_requires_zero_verifier_exit():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "The verifier must exit zero" in runbook
