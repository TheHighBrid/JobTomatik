from backend.scripts.verify_ashby_real_certification import verify


def test_duplicate_suppression_is_mandatory():
    blockers = verify({"adapter": "ashby", "duplicate_submission_suppressed": False})
    assert "duplicate_submission_not_suppressed" in blockers
