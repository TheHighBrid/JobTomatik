from backend.scripts.verify_ashby_real_certification import verify


def test_pending_status_cannot_certify_even_with_confirmation_flag():
    evidence = {
        "adapter": "ashby",
        "application_id": 99,
        "target_url": "https://jobs.ashbyhq.com/x/12345678-1234-4123-8123-123456789abc/application",
        "runtime": "android_native_chrome_cdp",
        "confirmation_sufficient": True,
        "confirmation_evidence_type": "success_banner",
        "confirmation_final_url": "https://jobs.ashbyhq.com/x/12345678-1234-4123-8123-123456789abc/application",
        "persisted_status": "pending",
        "duplicate_submission_suppressed": True,
        "unknown_answer_policy_respected": True,
        "retained_tab_resume_proven": True,
    }
    assert "status_not_applied" in verify(evidence)
