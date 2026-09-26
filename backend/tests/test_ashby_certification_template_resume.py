import json
from pathlib import Path


def test_template_does_not_preclaim_retained_tab_proof():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["retained_tab_resume_proven"] is False
