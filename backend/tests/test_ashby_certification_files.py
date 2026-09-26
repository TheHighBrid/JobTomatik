from pathlib import Path


def test_certification_artifacts_exist():
    required = [
        "docs/ASHBY_REAL_CERTIFICATION.md",
        "docs/ASHBY_CERTIFICATION_RUNBOOK.md",
        "docs/ashby-real-certification-evidence.example.json",
        "backend/scripts/verify_ashby_real_certification.py",
        ".github/workflows/ashby-real-certification-contract.yml",
    ]
    for item in required:
        assert Path(item).is_file(), item
