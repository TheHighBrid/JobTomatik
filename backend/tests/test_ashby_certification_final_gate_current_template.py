from pathlib import Path


def test_physical_gate_has_non_authoritative_template():
    path = Path("docs/ashby-real-certification-evidence.example.json")
    assert path.exists()
    assert path.name.endswith(".example.json")
