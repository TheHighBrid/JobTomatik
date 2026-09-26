import json
from pathlib import Path


def test_template_does_not_prefill_real_application_id():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["application_id"] == 0
