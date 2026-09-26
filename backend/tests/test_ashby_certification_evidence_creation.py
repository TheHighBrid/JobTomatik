from pathlib import Path


def test_runbook_requires_evidence_from_captured_facts():
    text = Path("docs/ASHBY_CERTIFICATION_RUNBOOK.md").read_text(encoding="utf-8")
    assert "from the supplied example schema using facts captured by the run" in text
