from pathlib import Path


def test_branch_contains_final_gate_tooling():
    assert Path("backend/scripts/verify_ashby_real_certification.py").exists()
    assert Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").exists()
    assert Path(".github/workflows/ashby-real-certification-contract.yml").exists()
