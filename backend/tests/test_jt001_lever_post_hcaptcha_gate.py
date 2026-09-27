"""JT-001 regression contract for the physical Lever post-hCaptcha path.

These tests intentionally do not solve or interact with CAPTCHA. They start at the
retained human-confirmation boundary and lock the employer evidence rules that must
hold after the owner completes the final action in native Chrome.
"""

import pytest

from app.models.handoff import HandoffChallengeType
from app.services import browser_handoff
from app.services.operator_assisted_handoff_integration import (
    install_operator_assisted_handoff_integration,
)


class _Body:
    def __init__(self, text: str):
        self._text = text

    async def inner_text(self):
        return self._text


class _Page:
    def __init__(self, *, url: str, body: str):
        self.url = url
        self._body = body

    def locator(self, selector: str):
        assert selector == "body"
        return _Body(self._body)


@pytest.mark.asyncio
async def test_jt001_physical_lever_thanks_page_is_explicit_confirmation():
    """Mirror the known physical evidence: Lever `/thanks` + `Application submitted!`."""

    state = await browser_handoff._submission_confirmation_state(
        _Page(
            url="https://jobs.lever.co/example/known-posting/thanks",
            body="Application submitted!",
        )
    )

    assert state["submission_confirmed"] is True
    assert state["matched_confirmation_phrases"] == ["application submitted"]
    assert len(state["confirmation_evidence"]) == 1
    assert state["confirmation_evidence"][0]["is_sufficient"] is True


@pytest.mark.asyncio
async def test_jt001_lever_thanks_route_without_explicit_confirmation_fails_closed():
    """A route transition alone must never promote an application to Applied."""

    state = await browser_handoff._submission_confirmation_state(
        _Page(
            url="https://jobs.lever.co/example/known-posting/thanks",
            body="Please wait while we finish processing your request.",
        )
    )

    assert state["submission_confirmed"] is False
    assert state["confirmation_evidence"] == []


@pytest.mark.asyncio
async def test_jt001_retained_human_confirmation_requires_verified_target(monkeypatch):
    """Explicit success text is insufficient if the retained target identity drifted."""

    install_operator_assisted_handoff_integration()

    async def generic_confirmation(_session):
        return browser_handoff.BrowserVerification(
            challenge_cleared=True,
            provider="local_cdp",
            current_url="https://jobs.lever.co/example/known-posting/thanks",
            current_fingerprint="post-human-submit",
            evidence={
                "submission_confirmed": True,
                "confirmation_url_signal": True,
                "confirmation_evidence": [{
                    "evidence_type": "confirmation_page",
                    "is_sufficient": True,
                    "confirmation_text": "application submitted",
                }],
                "target_verification": {"verified": False, "adapter": "lever"},
            },
        )

    import app.services.operator_assisted_handoff_integration as integration

    monkeypatch.setattr(integration, "_ORIGINAL_VERIFY_COMPLETION", generic_confirmation)
    session = type("Session", (), {
        "challenge_type": HandoffChallengeType.final_submit.value,
        "browser_provider": "local_cdp",
        "current_url": "https://jobs.lever.co/example/known-posting",
        "current_fingerprint": "pre-human-submit",
        "handoff_metadata": {},
    })()

    result = await browser_handoff.verify_browser_handoff_completion(session)

    assert result.challenge_cleared is False
    assert result.evidence["submission_confirmed"] is False
    assert result.evidence["retained_human_confirmation"] is False
