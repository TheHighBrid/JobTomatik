from backend.scripts.verify_ashby_real_certification import verify


def test_empty_evidence_fails_closed():
    blockers = verify({})
    assert len(blockers) >= 10
