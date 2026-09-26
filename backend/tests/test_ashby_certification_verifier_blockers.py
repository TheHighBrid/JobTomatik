from pathlib import Path


def test_verifier_has_explicit_blocker_codes():
    source = Path("backend/scripts/verify_ashby_real_certification.py").read_text(encoding="utf-8")
    for blocker in ("adapter_not_ashby", "missing_application_id", "target_not_ashby", "wrong_runtime", "confirmation_not_sufficient", "status_not_applied", "duplicate_submission_not_suppressed", "unknown_answer_policy_not_proven", "retained_tab_resume_not_proven"):
        assert blocker in source
