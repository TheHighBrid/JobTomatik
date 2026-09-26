from pathlib import Path


def test_evidence_template_is_ready_for_physical_facts():
    assert Path("docs/ashby-real-certification-evidence.example.json").is_file()
