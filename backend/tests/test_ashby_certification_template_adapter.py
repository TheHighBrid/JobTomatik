import json
from pathlib import Path


def test_template_binds_ashby_adapter():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["adapter"] == "ashby"
