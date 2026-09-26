from pathlib import Path


def test_workflow_name_is_explicit():
    workflow = Path(".github/workflows/ashby-real-certification-contract.yml").read_text(encoding="utf-8")
    assert workflow.startswith("name: Ashby real certification contract")
