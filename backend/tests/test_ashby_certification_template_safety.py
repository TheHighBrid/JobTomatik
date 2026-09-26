import json
from pathlib import Path


def test_template_does_not_preclaim_runtime_proofs():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["duplicate_submission_suppressed"] is False
    assert payload["unknown_answer_policy_respected"] is False
    assert payload["retained_tab_resume_proven"] is False
