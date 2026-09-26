from pathlib import Path


def test_certification_tooling_is_ready_for_physical_gate():
    assert Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").is_file()
    assert Path("backend/scripts/verify_ashby_real_certification.py").is_file()
    assert Path("docs/ashby-real-certification-evidence.example.json").is_file()
