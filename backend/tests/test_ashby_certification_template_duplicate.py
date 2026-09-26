import json
from pathlib import Path


def test_template_does_not_preclaim_duplicate_suppression():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["duplicate_submission_suppressed"] is False
