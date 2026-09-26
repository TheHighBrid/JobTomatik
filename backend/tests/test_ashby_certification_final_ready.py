from pathlib import Path


def test_branch_is_prepared_for_final_physical_gate():
    assert Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").exists()
    assert Path("backend/scripts/verify_ashby_real_certification.py").exists()
    assert Path("docs/ashby-real-certification-evidence.example.json").exists()
