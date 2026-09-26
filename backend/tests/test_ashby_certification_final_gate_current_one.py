from pathlib import Path


def test_physical_gate_requires_only_one_real_run():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert runbook.count("## One physical run") == 1
