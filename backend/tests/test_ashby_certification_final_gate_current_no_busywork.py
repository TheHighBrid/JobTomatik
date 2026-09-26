from pathlib import Path


def test_remaining_gate_avoids_repetitive_operator_work():
    runbook = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert runbook.count("## One physical run") == 1
