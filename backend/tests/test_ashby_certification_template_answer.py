import json
from pathlib import Path


def test_template_does_not_preclaim_answer_policy_proof():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["unknown_answer_policy_respected"] is False
