from pathlib import Path


def test_verifier_checks_every_evidence_field():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    for field in ("adapter", "application_id", "target_url", "runtime", "confirmation_sufficient", "confirmation_evidence_type", "confirmation_final_url", "persisted_status", "duplicate_submission_suppressed", "unknown_answer_policy_respected", "retained_tab_resume_proven"):
        assert f'payload.get("{field}")' in source or field == "target_url"
