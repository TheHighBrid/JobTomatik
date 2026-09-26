from pathlib import Path


def test_branch_head_has_required_artifacts():
    for path in ("docs/ASHBY_REAL_CERTIFICATION.md", "docs/ASHBY_CERTIFICATION_RUNBOOK.md", "docs/ashby-real-certification-evidence.example.json", "backend/scripts/verify_ashby_real_certification.py"):
        assert Path(path).exists()
