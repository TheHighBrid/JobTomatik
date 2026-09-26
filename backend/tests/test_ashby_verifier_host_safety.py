from backend.scripts.verify_ashby_real_certification import verify


def test_non_ashby_target_cannot_certify():
    blockers = verify({
        "adapter": "ashby",
        "application_id": 1,
        "target_url": "https://example.com/application",
        "runtime": "android_native_chrome_cdp",
        "confirmation_sufficient": True,
        "confirmation_evidence_type": "confirmation_page",
        "confirmation_final_url": "https://example.com/thanks",
        "persisted_status": "applied",
        "duplicate_submission_suppressed": True,
        "unknown_answer_policy_respected": True,
        "retained_tab_resume_proven": True,
    })
    assert "target_not_ashby" in blockers
