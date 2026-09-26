import json
from pathlib import Path


def test_template_does_not_prefill_confirmation():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["confirmation_evidence_type"] is None
    assert payload["confirmation_final_url"] is None
