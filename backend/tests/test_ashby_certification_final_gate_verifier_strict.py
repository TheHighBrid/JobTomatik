from backend.scripts.verify_ashby_real_certification import verify


def test_partial_evidence_cannot_satisfy_final_gate():
    blockers = verify({"adapter": "ashby", "runtime": "android_native_chrome_cdp"})
    assert blockers
    assert "missing_application_id" in blockers
    assert "confirmation_not_sufficient" in blockers
    assert "status_not_applied" in blockers
