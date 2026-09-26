from pathlib import Path


def test_workflow_names_fail_closed_gate():
    workflow = Path(".github/workflows/ashby-real-certification-contract.yml").read_text(encoding="utf-8")
    assert "Verify Ashby certification remains fail-closed until real evidence exists" in workflow
