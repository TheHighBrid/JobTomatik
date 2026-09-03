from types import SimpleNamespace

import pytest

from app.models.handoff import HandoffChallengeType
from app.services import browser_handoff
from app.services import operator_assisted_live_pilot_hardening as hardening
from app.services.operator_assisted_live_pilot_hardening import (
    passive_verification_requires_manual_browser,
    passive_verification_state,
)


class _Element:
    def __init__(self, *, src: str = "", value: str = ""):
        self._src = src
        self._value = value

    async def get_attribute(self, name: str):
        return self._src if name == "src" else None

    async def input_value(self):
        return self._value


class _PassivePage:
    def __init__(self, *, completed: bool):
        self.completed = completed

    async def evaluate(self, _script):
        return {"hcaptcha": True, "grecaptcha": True, "turnstile": False}

    async def query_selector_all(self, selector: str):
        if selector == 'textarea[name="h-captcha-response"]' and self.completed:
            return [_Element(value="x" * 40)]
        if selector == "iframe[src]":
            return [
                _Element(
                    src=(
                        "https://newassets.hcaptcha.com/captcha/v1/test/"
                        "static/hcaptcha-enclave.html"
                    )
                )
            ]
        return []


@pytest.mark.asyncio
async def test_passive_hcaptcha_without_response_requires_manual_browser():
    state = await passive_verification_state(_PassivePage(completed=False))

    assert state["hcaptcha_loaded"] is True
    assert state["has_completed_response"] is False
    assert state["manual_browser_required"] is True
    assert passive_verification_requires_manual_browser(state) is True


@pytest.mark.asyncio
async def test_completed_hcaptcha_response_does_not_force_manual_browser():
    state = await passive_verification_state(_PassivePage(completed=True))

    assert state["hcaptcha_loaded"] is True
    assert state["has_completed_response"] is True
    assert state["manual_browser_required"] is False
    assert passive_verification_requires_manual_browser(state) is False


@pytest.mark.asyncio
async def test_final_submit_confirmation_recursion_fails_closed(monkeypatch):
    hardening.install_operator_assisted_live_pilot_hardening()
    session = SimpleNamespace(
        challenge_type=HandoffChallengeType.final_submit.value,
        browser_provider="local_cdp",
        current_url="https://jobs.lever.co/example/posting/apply",
        current_fingerprint="before-submit",
    )

    async def recursive_verifier(current_session):
        return await browser_handoff.verify_browser_handoff_completion(current_session)

    monkeypatch.setattr(hardening, "_ORIGINAL_VERIFY_COMPLETION", recursive_verifier)

    result = await browser_handoff.verify_browser_handoff_completion(session)

    assert result.challenge_cleared is False
    assert result.evidence["submission_confirmed"] is False
    assert result.evidence["reentrant_verification_blocked"] is True
    assert result.evidence["automatic_retry_allowed"] is False
    assert result.evidence["verification_method"] == "operator_final_submit_reentrancy_blocked"
