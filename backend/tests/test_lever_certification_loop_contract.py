from __future__ import annotations

import pytest

from app.services.ats_lever import LeverAdapter


class _Element:
    def __init__(self, *, text="", visible=True, enabled=True):
        self._text = text
        self._visible = visible
        self._enabled = enabled
        self.clicked = False

    async def is_visible(self):
        return self._visible

    async def is_enabled(self):
        return self._enabled

    async def inner_text(self):
        return self._text

    async def get_attribute(self, _name):
        return None

    async def click(self):
        self.clicked = True


class _Surface:
    def __init__(self, *, url, body, submit=None, confirmation=None):
        self.url = url
        self.body = body
        self.submit = submit
        self.confirmation = confirmation

    async def query_selector(self, selector):
        if "submit" in selector or "postings-btn" in selector:
            return self.submit
        if "confirmation" in selector:
            return self.confirmation
        return None

    async def query_selector_all(self, _selector):
        return []

    async def inner_text(self, selector):
        if selector == "body":
            return self.body
        return ""


@pytest.mark.asyncio
async def test_lever_final_submit_control_is_discoverable_for_authorized_live_run(monkeypatch):
    adapter = LeverAdapter()
    submit = _Element(text="Submit application")
    surface = _Surface(
        url="https://jobs.lever.co/example/posting/apply",
        body="Application form",
        submit=submit,
    )

    monkeypatch.setattr(adapter, "capture_pre_submit_confirmation_state", lambda *_: _async({}))
    found = await adapter.find_submit_button(surface)
    assert found is submit


@pytest.mark.asyncio
async def test_explicit_lever_confirmation_is_sufficient_after_real_submit(monkeypatch):
    adapter = LeverAdapter()
    confirmation = _Element(text="Application submitted! Thank you for applying.")
    surface = _Surface(
        url="https://jobs.lever.co/example/posting/thanks",
        body="Application submitted! Thank you for applying.",
        confirmation=confirmation,
    )

    async def fingerprint(_surface):
        return "after"

    async def no_submit(_surface):
        return False

    monkeypatch.setattr(adapter, "step_fingerprint", fingerprint)
    monkeypatch.setattr(adapter, "visible_submit_control_present", no_submit)
    evidence = await adapter.detect_confirmation(
        surface,
        before_url="https://jobs.lever.co/example/posting/apply",
        before_fingerprint="before",
    )

    assert any(item.is_sufficient for item in evidence)
    accepted = next(item for item in evidence if item.is_sufficient)
    assert accepted.final_url.endswith("/thanks")
    assert "application submitted" in accepted.confirmation_text.lower()


@pytest.mark.asyncio
async def test_confirmation_route_without_confirmation_copy_is_not_success(monkeypatch):
    adapter = LeverAdapter()
    surface = _Surface(
        url="https://jobs.lever.co/example/posting/thanks",
        body="Thanks for visiting our careers site.",
    )

    async def fingerprint(_surface):
        return "after"

    async def no_submit(_surface):
        return False

    monkeypatch.setattr(adapter, "step_fingerprint", fingerprint)
    monkeypatch.setattr(adapter, "visible_submit_control_present", no_submit)
    evidence = await adapter.detect_confirmation(
        surface,
        before_url="https://jobs.lever.co/example/posting/apply",
        before_fingerprint="before",
    )

    assert not any(item.is_sufficient for item in evidence)


async def _async(value):
    return value
