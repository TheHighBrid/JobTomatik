from types import SimpleNamespace

import pytest

from app.services import operational_safety as safety


URL = "https://jobs.lever.co/synthetic/12345678-1234-1234-1234-123456789abc"


@pytest.mark.parametrize("legacy", [False, True])
def test_lever_handoff_binds_posting_across_apply_and_thanks(monkeypatch, legacy):
    monkeypatch.setattr(safety, "require_browser_entry_allowed", lambda url: None)
    binding = {
        "platform": "lever", "expected_url": URL + "/apply",
        "posting_identity": "lever:jobs.lever.co:apply" if legacy else safety._posting_identity(URL + "/apply"),
    }
    session = SimpleNamespace(handoff_metadata={"target_binding": binding})
    assert safety.require_bound_handoff_url(session, URL + "/thanks").allowed
    assert safety._posting_identity(URL) == safety._posting_identity(URL + "/apply")
    assert safety._posting_identity(URL) == safety._posting_identity(URL + "/thanks")
    for suffix in ("apply", "thanks"):
        with pytest.raises(safety.OperationalSafetyViolation, match="different posting"):
            safety.require_bound_handoff_url(session, URL.replace("123456789abc", "000000000000") + "/" + suffix)
