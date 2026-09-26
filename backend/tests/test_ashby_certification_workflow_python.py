from pathlib import Path


def test_workflow_uses_python_312():
    workflow = Path(".github/workflows/ashby-real-certification-contract.yml").read_text(encoding="utf-8")
    assert 'python-version: "3.12"' in workflow
