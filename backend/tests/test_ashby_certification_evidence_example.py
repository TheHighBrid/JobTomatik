import json
from pathlib import Path


def test_example_is_non_authoritative():
    path = Path("docs/ashby-real-certification-evidence.example.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.name.endswith(".example.json")
    assert payload["application_id"] == 0
    assert payload["confirmation_sufficient"] is False
