from pathlib import Path


def test_workflow_supports_manual_dispatch():
    workflow = Path(".github/workflows/ashby-real-certification-contract.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
