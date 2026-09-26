import json
from pathlib import Path


def test_template_starts_pending():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["persisted_status"] == "pending"
    assert payload["confirmation_sufficient"] is False
