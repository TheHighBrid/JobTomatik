from pathlib import Path


def test_workflow_watches_certification_surfaces():
    workflow = Path(".github/workflows/ashby-real-certification-contract.yml").read_text(encoding="utf-8")
    for path in ("backend/app/services/ats_ashby.py", "docs/ASHBY_REAL_CERTIFICATION.md", "test_ashby_real_certification_contract.py"):
        assert path in workflow
