from types import SimpleNamespace

import pytest

from app.services.operator_assisted_live_pilot_hardening import (
    _verify_final_submit_without_wrapper_chain,
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


class _Context:
    async def storage_state(self):
        return {"cookies": [], "origins": []}


class _Playwright:
    pass


class _Page:
    url = "https://jobs.lever.co/example/posting/thanks"


class _Verification:
    def __init__(
        self,
        *,
        challenge_cleared,
        provider,
        current_url,
        current_fingerprint,
        evidence,
    ):
        self.challenge_cleared = challenge_cleared
        self.provider = provider
        self.current_url = current_url
        self.current_fingerprint = current_fingerprint
        self.evidence = evidence


@pytest.mark.asyncio
async def test_final_submit_verification_is_self_contained_and_does_not_delegate():
    page = _Page()
    playwright = _Playwright()
    disconnected = []

    async def connect(_session):
        return playwright, object(), _Context(), page

    async def disconnect(value):
        disconnected.append(value)

    async def fingerprint(_page):
        return "post-submit-fingerprint"

    async def confirmation(_page):
        return {
            "submission_confirmed": True,
            "confirmation_url_signal": True,
            "matched_confirmation_phrases": ["application submitted"],
            "confirmation_evidence": [],
        }

    async def target(_page, _session, **_kwargs):
        return {"verified": True, "blockers": []}

    fake_browser_handoff = SimpleNamespace(
        _connect_local_cdp=connect,
        _disconnect=disconnect,
        page_fingerprint=fingerprint,
        _submission_confirmation_state=confirmation,
        _verify_session_target=target,
        BrowserVerification=_Verification,
    )
    session = SimpleNamespace(
        browser_provider="local_cdp",
        handoff_metadata={
            "operator_submit_live_snapshot_checkpointed": True,
            "operator_submit_pre_submit_url": (
                "https://jobs.lever.co/example/posting/apply"
            ),
            "operator_submit_confirmation_observed": False,
        },
    )

    result = await _verify_final_submit_without_wrapper_chain(
        fake_browser_handoff,
        session,
    )

    assert result.challenge_cleared is True
    assert result.evidence["submission_confirmed"] is True
    assert result.evidence["provable_confirmation_transition"] is True
    assert disconnected == [playwright]
