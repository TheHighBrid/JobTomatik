from pathlib import Path


def test_workflow_checks_out_revision():
    workflow = Path(".github/workflows/ashby-real-certification-contract.yml").read_text(encoding="utf-8")
    assert "actions/checkout@v4" in workflow
