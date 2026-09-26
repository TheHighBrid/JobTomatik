from backend.scripts.verify_ashby_real_certification import verify


def test_wrong_adapter_is_rejected():
    assert "adapter_not_ashby" in verify({"adapter": "lever"})
