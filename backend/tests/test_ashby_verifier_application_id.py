from backend.scripts.verify_ashby_real_certification import verify


def test_application_identity_is_required():
    assert "missing_application_id" in verify({"adapter": "ashby", "application_id": None})
