from pathlib import Path


def test_all_final_gate_tooling_exists():
    assert all(Path(path).exists() for path in (
        "docs/ASHBY_REAL_CERTIFICATION.md",
        "docs/ASHBY_CERTIFICATION_RUNBOOK.md",
        "docs/ashby-real-certification-evidence.example.json",
        "backend/scripts/verify_ashby_real_certification.py",
        ".github/workflows/ashby-real-certification-contract.yml",
    ))
