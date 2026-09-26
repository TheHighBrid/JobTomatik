from backend.scripts.verify_ashby_real_certification import verify


def test_complete_evidence_can_pass():
    payload = {
        "adapter": "ashby",
        "application_id": 291,
        "target_url": "https://jobs.ashbyhq.com/acme/12345678-1234-4123-8123-123456789abc/application",
        "runtime": "android_native_chrome_cdp",
        "confirmation_sufficient": True,
        "confirmation_evidence_type": "confirmation_page",
        "confirmation_final_url": "https://jobs.ashbyhq.com/acme/12345678-1234-4123-8123-123456789abc/application",
        "persisted_status": "applied",
        "duplicate_submission_suppressed": True,
        "unknown_answer_policy_respected": True,
        "retained_tab_resume_proven": True,
    }
    assert verify(payload) == []
