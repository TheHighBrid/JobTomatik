import json
from pathlib import Path


def test_evidence_template_contains_all_required_fields():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    required = {
        "adapter",
        "application_id",
        "target_url",
        "runtime",
        "confirmation_sufficient",
        "confirmation_evidence_type",
        "confirmation_final_url",
        "persisted_status",
        "duplicate_submission_suppressed",
        "unknown_answer_policy_respected",
        "retained_tab_resume_proven",
    }
    assert required == set(payload)
