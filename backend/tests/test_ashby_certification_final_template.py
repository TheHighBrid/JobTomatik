import json
from pathlib import Path


def test_branch_head_template_is_noncertifying():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["confirmation_sufficient"] is False
    assert payload["persisted_status"] == "pending"
