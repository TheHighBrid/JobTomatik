from backend.scripts.verify_ashby_real_certification import verify


def test_branch_head_verifier_fails_closed_without_evidence():
    assert verify({})
