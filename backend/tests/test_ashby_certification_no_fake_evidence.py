from pathlib import Path


def test_example_is_not_written_to_authoritative_evidence_path():
    assert Path("docs/ashby-real-certification-evidence.example.json").exists()
    assert not Path("evidence/ashby-real-certification.json").exists()
