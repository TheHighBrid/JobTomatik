import pytest

from app.models.handoff import ManualHandoffSession
from app.schemas.handoff import HandoffBrowserActionRequest
from app.services import browser_handoff


class FakeKeyboard:
    def __init__(self):
        self.calls = []

    async def press(self, key):
        self.calls.append(("press", key))

    async def insert_text(self, text):
        self.calls.append(("insert_text", text))


class FakeMouse:
    async def click(self, *_args, **_kwargs):
        return None

    async def wheel(self, *_args, **_kwargs):
        return None


class FakePage:
    def __init__(self):
        self.keyboard = FakeKeyboard()
        self.mouse = FakeMouse()
        self.url = "https://example.test/verify"
        self.waited = []

    async def wait_for_timeout(self, milliseconds):
        self.waited.append(milliseconds)


@pytest.mark.asyncio
async def test_replace_and_submit_clears_old_code_before_enter(monkeypatch):
    page = FakePage()

    async def fake_connect(_session):
        return object(), object(), object(), page

    async def fake_disconnect(_playwright):
        return None

    async def fake_fingerprint(_page):
        return "after-new-code"

    monkeypatch.setattr(browser_handoff, "_connect_local_cdp", fake_connect)
    monkeypatch.setattr(browser_handoff, "_disconnect", fake_disconnect)
    monkeypatch.setattr(browser_handoff, "page_fingerprint", fake_fingerprint)

    result = await browser_handoff.perform_handoff_action(
        ManualHandoffSession(browser_provider="local_cdp"),
        action="replace_and_submit",
        text="654321",
    )

    assert page.keyboard.calls == [
        ("press", "Control+A"),
        ("insert_text", "654321"),
        ("press", "Enter"),
    ]
    assert page.waited == [750]
    assert result["action"] == "replace_and_submit"
    assert result["sensitive_value_logged"] is False


def test_recovery_actions_are_validated_by_api_schema():
    lease = "x" * 24
    for action in ("replace_and_submit", "resend_code", "back", "reload"):
        payload = HandoffBrowserActionRequest(
            lease_token=lease,
            action=action,
            text="123456" if action == "replace_and_submit" else None,
        )
        assert payload.action == action
