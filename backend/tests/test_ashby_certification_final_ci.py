from pathlib import Path


def test_branch_head_has_dedicated_ci_gate():
    assert Path(".github/workflows/ashby-real-certification-contract.yml").exists()
