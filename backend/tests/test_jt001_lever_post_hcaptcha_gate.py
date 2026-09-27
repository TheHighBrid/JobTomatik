"""
JT-001 regression contract for the physical Lever post-hCaptcha path.

These tests intentionally do not solve or interact with CAPTCHA. They start at the
retained human-confirmation boundary and lock the employer evidence rules that must
hold after the owner completes the final action in native Chrome.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.handoff import HandoffChallengeType
from app.services import browser_handoff
from app.services import operator_assisted_handoff_integration as integration


@pytest.fixture
def isolated_handoff_integration(monkeypatch):
    """Install against public test doubles and restore every patched integration point."""
    from app.api import handoffs
    from app.services import form_filler_handoff, handoff_integration, handoff_session
    from app.tasks import applications

    points = (
        (form_filler_handoff, "run_ats_application_flow"),
        (applications, "fill_and_submit_application"),
        (handoff_session, "claim_handoff_session"),
        (browser_handoff, "perform_handoff_action"),
        (browser_handoff, "verify_browser_handoff_completion"),
        (handoffs, "claim_handoff_session"),
        (handoffs, "perform_handoff_action"),
        (handoffs, "verify_browser_handoff_completion"),
    )
    with monkeypatch.context() as isolated:
        for module, name in points:
            isolated.setattr(module, name, getattr(module, name))
        for module, name in (
            (form_filler_handoff, "_RESUMABLE_REASONS"),
            (handoff_integration, "_RESUMABLE_REASON_VALUES"),
            (handoff_session, "_ALLOWED_REASON_TO_CHALLENGE"),
        ):
            isolated.setattr(module, name, getattr(module, name).copy())

        # The installer remembers its original public callbacks in module globals.
        # Restore that entire namespace, including its installation flag, at teardown.
        with patch.dict(vars(integration), {"_INSTALLED": False}):
            def install(verification):
                async def verify_completion(_session):
                    return verification

                isolated.setattr(
                    browser_handoff, "verify_browser_handoff_completion", verify_completion
                )
                integration.install_operator_assisted_handoff_integration()

            yield install


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
@pytest.mark.parametrize(
    ("route", "url_signal", "evidence_type"),
    [("thanks", True, "confirmation_page"), ("apply", False, "success_banner")],
)
async def test_jt001_physical_lever_thanks_page_is_explicit_confirmation(
    route, url_signal, evidence_type
):
    """Mirror the known physical evidence: Lever `/thanks` + `Application submitted!`."""
    state = await browser_handoff._submission_confirmation_state(
        _Page(
            url=f"https://jobs.lever.co/example/known-posting/{route}",
            body="Application submitted!",
        )
    )

    assert state["submission_confirmed"] is True
    assert state["confirmation_url_signal"] is url_signal
    assert state["matched_confirmation_phrases"] == ["application submitted"]
    assert len(state["confirmation_evidence"]) == 1
    assert state["confirmation_evidence"][0]["is_sufficient"] is True
    assert state["confirmation_evidence"][0]["evidence_type"] == evidence_type
    assert state["confirmation_evidence"][0]["metadata"]["confirmation_url_signal"] is url_signal


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
    assert state["confirmation_url_signal"] is True
    assert state["confirmation_evidence"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("target_verified", [False, True])
async def test_jt001_retained_human_confirmation_requires_verified_target(
    isolated_handoff_integration, target_verified
):
    """Explicit success text is insufficient if the retained target identity drifted."""
    isolated_handoff_integration(
        browser_handoff.BrowserVerification(
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
                "target_verification": {"verified": target_verified, "adapter": "lever"},
            },
        )
    )
    session = SimpleNamespace(**{
        "challenge_type": HandoffChallengeType.final_submit.value,
        "browser_provider": "local_cdp",
        "current_url": "https://jobs.lever.co/example/known-posting",
        "current_fingerprint": "pre-human-submit",
        "handoff_metadata": {},
    })

    result = await browser_handoff.verify_browser_handoff_completion(session)

    assert result.challenge_cleared is target_verified
    assert result.evidence["submission_confirmed"] is target_verified
    assert result.evidence["retained_human_confirmation"] is target_verified
