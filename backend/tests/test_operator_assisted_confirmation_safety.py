import pytest

from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.services import browser_handoff
from app.services import operator_assisted_handoff_integration as integration


LEVER_URL = "https://jobs.lever.co/safeco/posting-123/apply"


def _session(*, strong_confirmation: bool = False) -> ManualHandoffSession:
    return ManualHandoffSession(
        application_id=1,
        manual_review_id=1,
        user_id=1,
        challenge_type=HandoffChallengeType.final_submit.value,
        status="claimed",
        idempotency_key="strict-confirmation-test",
        resume_token_hash="hash",
        encrypted_resume_token="encrypted",
        resume_token_prefix="prefix",
        browser_provider="local_cdp",
        current_url=LEVER_URL,
        current_fingerprint="after-submit",
        handoff_metadata={
            "operator_submit_pre_submit_url": LEVER_URL,
            "operator_submit_pre_submit_fingerprint": "before-submit",
            "operator_submit_confirmation_observed": strong_confirmation,
            "automatic_retry_allowed": False,
        },
    )


@pytest.mark.asyncio
async def test_generic_confirmation_copy_alone_cannot_clear_operator_final_submit(monkeypatch):
    integration.install_operator_assisted_handoff_integration()

    async def generic_false_positive(_session):
        return browser_handoff.BrowserVerification(
            challenge_cleared=True,
            provider="local_cdp",
            current_url=LEVER_URL,
            current_fingerprint="after-submit",
            evidence={
                "submission_confirmed": True,
                "confirmation_url_signal": False,
                "target_verification": {"verified": True, "blockers": []},
                "verification_method": "explicit_submission_confirmation",
            },
        )

    monkeypatch.setattr(integration, "_ORIGINAL_VERIFY_COMPLETION", generic_false_positive)
    result = await browser_handoff.verify_browser_handoff_completion(_session())

    assert result.challenge_cleared is False
    assert result.evidence["submission_confirmed"] is False
    assert result.evidence["operator_submit_confirmation_observed"] is False
    assert result.evidence["provable_confirmation_transition"] is False
    assert result.evidence["verification_method"] == "operator_final_submit_confirmation_required"


@pytest.mark.asyncio
async def test_strict_lever_confirmation_observed_by_final_action_can_clear_handoff(monkeypatch):
    integration.install_operator_assisted_handoff_integration()

    async def target_still_verified(_session):
        return browser_handoff.BrowserVerification(
            challenge_cleared=False,
            provider="local_cdp",
            current_url="https://jobs.lever.co/safeco/thank-you",
            current_fingerprint="confirmed-submit",
            evidence={
                "submission_confirmed": False,
                "confirmation_url_signal": True,
                "target_verification": {"verified": True, "blockers": []},
                "verification_method": "browser_state",
            },
        )

    monkeypatch.setattr(integration, "_ORIGINAL_VERIFY_COMPLETION", target_still_verified)
    result = await browser_handoff.verify_browser_handoff_completion(
        _session(strong_confirmation=True)
    )

    assert result.challenge_cleared is True
    assert result.evidence["submission_confirmed"] is True
    assert result.evidence["operator_submit_confirmation_observed"] is True
    assert result.evidence["verification_method"] == "operator_final_submit_strict_confirmation"
