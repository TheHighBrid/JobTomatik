from pathlib import Path


def test_dedicated_workflow_runs_fail_closed_contract():
    workflow = Path(".github/workflows/ashby-real-certification-contract.yml").read_text(encoding="utf-8")
    assert "Ashby real certification contract" in workflow
    assert "test_ashby_real_certification_contract.py" in workflow
