import pytest

from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.services import browser_handoff


class _FakeLocator:
    def __init__(self, text):
        self._text = text

    async def inner_text(self):
        return self._text


class _FakePage:
    def __init__(self):
        self.url = (
            "https://job-boards.greenhouse.io/embed/job_app/confirmation"
            "?for=fanduel&token=7951203"
        )

    def locator(self, selector):
        assert selector == "body"
        return _FakeLocator(
            "Thank you for applying. Your application has been received. "
            "If there is a fit, someone will be getting back to you."
        )


class _FakeContext:
    async def storage_state(self):
        return {"cookies": [], "origins": []}


class _FakePlaywright:
    async def stop(self):
        return None


@pytest.mark.asyncio
async def test_greenhouse_confirmation_page_outweighs_missing_captcha_response(monkeypatch):
    page = _FakePage()
    session = ManualHandoffSession(
        public_id="confirmation-test",
        application_id=1,
        manual_review_id=1,
        user_id=1,
        challenge_type=HandoffChallengeType.captcha.value,
        browser_provider="local_cdp",
    )

    async def fake_connect(_session):
        return _FakePlaywright(), object(), _FakeContext(), page

    async def fake_fingerprint(_page):
        return "confirmation-fingerprint"

    monkeypatch.setattr(browser_handoff, "_connect_local_cdp", fake_connect)
    monkeypatch.setattr(browser_handoff, "page_fingerprint", fake_fingerprint)

    verification = await browser_handoff.verify_browser_handoff_completion(session)

    assert verification.challenge_cleared is True
    assert verification.current_url.endswith("for=fanduel&token=7951203")
    assert verification.evidence["submission_confirmed"] is True
    assert verification.evidence["verification_method"] == "explicit_submission_confirmation"
    evidence = verification.evidence["confirmation_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["evidence_type"] == "confirmation_page"
    assert evidence[0]["is_sufficient"] is True
    assert evidence[0]["confirmation_text"] == "thank you for applying"


@pytest.mark.asyncio
async def test_resume_short_circuits_on_confirmation_even_when_handoff_started_as_dry_run(monkeypatch):
    page = _FakePage()
    session = ManualHandoffSession(
        public_id="confirmation-resume-test",
        application_id=1,
        manual_review_id=1,
        user_id=1,
        challenge_type=HandoffChallengeType.captcha.value,
        browser_provider="local_cdp",
        handoff_metadata={"dry_run": True, "adapter": "greenhouse", "adapter_version": "1.1.1"},
    )

    async def fake_connect(_session):
        return _FakePlaywright(), object(), _FakeContext(), page

    monkeypatch.setattr(browser_handoff, "_connect_local_cdp", fake_connect)

    result = await browser_handoff.resume_handoff_application(
        session,
        user_profile={},
        cover_letter="",
        resume_path="",
        dry_run=True,
    )

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["submission_confirmed"] is True
    assert result["ready_to_submit"] is False
    assert result["requires_manual_review"] is False
    assert result["ats_adapter"] == "greenhouse"
    assert result["confirmation_evidence"][0]["is_sufficient"] is True
    assert any(
        item["action"] == "handoff_submission_confirmation_detected"
        for item in result["log"]
    )
