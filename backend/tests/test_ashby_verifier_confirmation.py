from backend.scripts.verify_ashby_real_certification import verify


def test_confirmation_type_and_final_url_are_required():
    evidence = {
        "adapter": "ashby",
        "application_id": 5,
        "target_url": "https://jobs.ashbyhq.com/x/12345678-1234-4123-8123-123456789abc/application",
        "runtime": "android_native_chrome_cdp",
        "confirmation_sufficient": True,
        "confirmation_evidence_type": "",
        "confirmation_final_url": "",
        "persisted_status": "applied",
        "duplicate_submission_suppressed": True,
        "unknown_answer_policy_respected": True,
        "retained_tab_resume_proven": True,
    }
    blockers = verify(evidence)
    assert "missing_confirmation_evidence_type" in blockers
    assert "missing_confirmation_final_url" in blockers
