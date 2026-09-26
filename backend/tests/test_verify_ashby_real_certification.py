from backend.scripts.verify_ashby_real_certification import verify


def valid_evidence():
    return {
        "adapter": "ashby",
        "application_id": 1,
        "target_url": "https://jobs.ashbyhq.com/example/12345678-1234-4123-8123-123456789abc/application",
        "runtime": "android_native_chrome_cdp",
        "confirmation_sufficient": True,
        "confirmation_evidence_type": "confirmation_page",
        "confirmation_final_url": "https://jobs.ashbyhq.com/example/12345678-1234-4123-8123-123456789abc/application",
        "persisted_status": "applied",
        "duplicate_submission_suppressed": True,
        "unknown_answer_policy_respected": True,
        "retained_tab_resume_proven": True,
    }


def test_complete_real_evidence_passes():
    assert verify(valid_evidence()) == []


def test_missing_confirmation_fails_closed():
    evidence = valid_evidence()
    evidence["confirmation_sufficient"] = False
    evidence["persisted_status"] = "pending"
    blockers = verify(evidence)
    assert "confirmation_not_sufficient" in blockers
    assert "status_not_applied" in blockers


def test_wrong_runtime_and_duplicate_failure_are_blockers():
    evidence = valid_evidence()
    evidence["runtime"] = "github_actions"
    evidence["duplicate_submission_suppressed"] = False
    blockers = verify(evidence)
    assert "wrong_runtime" in blockers
    assert "duplicate_submission_not_suppressed" in blockers
