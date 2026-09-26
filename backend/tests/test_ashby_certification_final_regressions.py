from pathlib import Path


def test_branch_head_final_promotion_requires_regressions():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "Run the Ashby adapter, handoff, confirmation, answer-policy, duplicate-suppression, and certification-contract regression suites before merge" in runbook
