from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import owner_browser_input as owner


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [
    "", "https://evil.test/?hcaptcha.com", "https://hcaptcha.com.evil.test/",
    "http://hcaptcha.com/", "https://google.com/not-verification",
])
async def test_owner_click_rejects_answers_submit_and_spoofed_provider(source, monkeypatch):
    page = SimpleNamespace(evaluate=AsyncMock(return_value=source))
    click = AsyncMock()
    monkeypatch.setattr(owner, "click_owner_viewport", click)
    with pytest.raises(owner.OwnerBrowserInputUnavailable, match="Only verification"):
        await owner.click_owner_verification(page, object(), x=20, y=30)
    click.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_verification_forwards_one_event_without_inspecting_challenge(monkeypatch):
    page = SimpleNamespace(evaluate=AsyncMock(return_value="https://newassets.hcaptcha.com/captcha/v1/frame"))
    click = AsyncMock()
    monkeypatch.setattr(owner, "click_owner_viewport", click)
    session = object()
    await owner.click_owner_verification(page, session, x=20, y=30)
    click.assert_awaited_once_with(page, session, x=20, y=30)


@pytest.mark.asyncio
async def test_native_submit_rejects_covered_control(monkeypatch):
    control = SimpleNamespace(
        scroll_into_view_if_needed=AsyncMock(),
        bounding_box=AsyncMock(return_value={"x": 50, "y": 100, "width": 200, "height": 40}),
        evaluate=AsyncMock(return_value=False),
    )
    click = AsyncMock()
    monkeypatch.setattr(owner, "click_owner_viewport", click)
    with pytest.raises(owner.OwnerBrowserInputUnavailable, match="covered"):
        await owner.click_owner_submit(object(), object(), control)
    click.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_input_rejects_headless_or_reused_pid(monkeypatch):
    monkeypatch.setenv("HANDOFF_NATIVE_INPUT_ENABLED", "true")
    monkeypatch.setenv("DISPLAY", ":99")
    session = SimpleNamespace(browser_provider="local_cdp", browser_process_id=1234, browser_profile_path="/state/profile")
    for command in (b"chrome\0--user-data-dir=/wrong\0", b"chrome\0--headless=new\0--user-data-dir=/state/profile\0"):
        monkeypatch.setattr(owner.Path, "read_bytes", lambda _path: command)
        with pytest.raises(owner.OwnerBrowserInputUnavailable, match="headless or its profile identity changed"):
            await owner.require_owner_window(session)


@pytest.mark.asyncio
async def test_native_input_refuses_mismatched_window_geometry(monkeypatch):
    monkeypatch.setattr(owner, "require_owner_window", AsyncMock(return_value="123"))
    monkeypatch.setattr(owner, "_xdotool", AsyncMock(return_value="X=0\nY=0\nWIDTH=800\nHEIGHT=700"))
    page = SimpleNamespace(
        bring_to_front=AsyncMock(), evaluate=AsyncMock(return_value={
            "x": 0, "y": 0, "width": 1280, "height": 980,
            "viewportWidth": 1280, "viewportHeight": 900, "scale": 1,
        }),
    )
    with pytest.raises(owner.OwnerBrowserInputUnavailable, match="geometry changed"):
        await owner.click_owner_viewport(page, object(), x=10, y=20)
    assert owner._xdotool.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("native,manual,reconcile,confirmed,available", [
    (False, False, False, False, True),
    (False, True, False, False, False),
    (True, True, False, False, True),
    (True, True, True, False, False),
    (True, False, False, True, False),
])
async def test_capabilities_preserve_review_and_confirmation_submit_boundaries(
    monkeypatch, native, manual, reconcile, confirmed, available,
):
    from app.services import browser_handoff, operator_assisted_live_pilot_hardening as hardening

    page = object()
    connection = object()
    monkeypatch.setattr(browser_handoff, "_connect_local_cdp", AsyncMock(return_value=(connection, None, None, page)))
    monkeypatch.setattr(browser_handoff, "_disconnect", AsyncMock())
    monkeypatch.setattr(browser_handoff, "_submission_confirmation_state", AsyncMock(return_value={"submission_confirmed": confirmed}))
    monkeypatch.setattr(browser_handoff, "_verify_session_target", AsyncMock(return_value={"verified": True, "blockers": []}))
    monkeypatch.setattr(hardening, "passive_verification_state", AsyncMock(return_value={"manual_browser_required": manual}))
    window = AsyncMock(return_value="123") if native else AsyncMock(side_effect=owner.OwnerBrowserInputUnavailable("Display stopped"))
    monkeypatch.setattr(owner, "require_owner_window", window)
    session = SimpleNamespace(handoff_metadata={"confirmation_reconciliation_required": reconcile})

    result = await owner.owner_handoff_capabilities(session)

    assert result["submit_available"] is available
    assert result["confirmation_visible"] is confirmed
    assert result["owner_pointer_enabled"] is native
    if reconcile:
        assert result["blocked_reason"] == "Review the retained outcome before any new submission."
    elif manual and not native:
        assert result["blocked_reason"] == "Display stopped"
    browser_handoff._disconnect.assert_awaited_once_with(connection)
