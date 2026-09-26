from backend.scripts.verify_ashby_real_certification import verify


def test_ci_or_synthetic_runtime_cannot_certify():
    blockers = verify({"adapter": "ashby", "runtime": "synthetic_playwright"})
    assert "wrong_runtime" in blockers
