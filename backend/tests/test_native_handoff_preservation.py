"""A refused native lease must preserve the application at its human boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import playwright.async_api
import pytest
from app.services import application_target_resolver, form_filler_handoff


@pytest.mark.asyncio
@pytest.mark.parametrize("producer", ["target", "form"])
@pytest.mark.parametrize("failure", ["missing_identity", "snapshot", "none"])
@pytest.mark.parametrize("native", [True, False])
async def test_native_security_boundary_preserves_page_when_handoff_fails(
    monkeypatch, producer, failure, native
):
    url = "https://www.linkedin.com/jobs/view/1234567890"
    challenge = {"reason_code": "captcha_detected", "summary": "Human action required"}
    page = SimpleNamespace(
        url=url,
        goto=AsyncMock(),
        wait_for_load_state=AsyncMock(),
        close=AsyncMock(),
        is_closed=lambda: False,
    )
    runtime = SimpleNamespace(
        page=page,
        owns_process=not native,
        terminate=MagicMock(),
        _jobtomatik_controlled_page_owned=True,
        browser=SimpleNamespace(_jobtomatik_application_browser_identity={
            "provider": "native_chrome" if native else "local",
            "browser_instance_id": (
                "" if failure == "missing_identity" else "4e7db6bc-2b5b-48d8-9acd-4a78d857cd1f"
            ),
        }),
        capture_snapshot=AsyncMock(return_value={
            "browser_provider": "local_cdp",
            "browser_session_id": "test-session",
            "current_url": url,
            "current_fingerprint": "test-fingerprint",
        }),
    )
    if failure == "snapshot":
        runtime.capture_snapshot.side_effect = OSError("snapshot storage unavailable")
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=SimpleNamespace())
    manager.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(playwright.async_api, "async_playwright", lambda: manager)
    module = application_target_resolver if producer == "target" else form_filler_handoff
    monkeypatch.setattr(module, "launch_application_browser", AsyncMock(return_value=runtime))
    monkeypatch.setattr(module, "open_application_entry", AsyncMock(return_value={}))
    monkeypatch.setattr(module, "detect_blocking_challenge", AsyncMock(return_value=challenge))
    if producer == "target":
        monkeypatch.setattr(module, "detect_closed_listing", AsyncMock(return_value=None))
        monkeypatch.setattr(module, "_controlled_page_target_id", AsyncMock(return_value="" if failure == "missing_identity" else "page-id"))
        result = await module.resolve_application_target_with_browser(url)
    else:
        monkeypatch.setattr(module, "controlled_page_target_id", AsyncMock(return_value="" if failure == "missing_identity" else "page-id"))
        monkeypatch.setattr(module, "detect_ats_adapter", AsyncMock(
            return_value=SimpleNamespace(name="generic", version="1")
        ))
        monkeypatch.setattr(module, "application_form_evidence", AsyncMock(
            return_value=SimpleNamespace(present=True, as_dict=lambda: {"present": True})
        ))
        flow = SimpleNamespace(
            success=False, requires_manual_review=True, review_items=[challenge],
            adapter_name="generic", adapter_version="1",
            as_dict=lambda: {
                "success": False, "requires_manual_review": True,
                "review_items": [challenge], "fields_filled": 3,
            },
        )
        monkeypatch.setattr(module, "run_ats_application_flow", AsyncMock(return_value=flow))
        result = await module.fill_and_submit_application_with_handoff(url, {}, "", "")
        assert result["fields_filled"] == 3

    # Exercise real cleanup, not a mocked release function: the controlled tab stays open.
    page.close.assert_not_awaited()
    assert runtime._jobtomatik_controlled_page_owned is True
    preserved = any(item.get("action") == "controlled_application_page_preserved" for item in result["log"])
    assert preserved is native
    if not native and failure == "snapshot":
        runtime.terminate.assert_called_once_with(remove_profile=False)
    else:
        runtime.terminate.assert_not_called()
    assert result["requires_manual_review"] is True
    assert result["success"] is False
    assert result["submitted_at"] is None
    assert result["review_items"] == [challenge]
    if failure == "missing_identity" and native:
        assert "RETAIN_IDENTITY_UNAVAILABLE" in result["error"]
        assert result["handoff_snapshot"] is None
        runtime.capture_snapshot.assert_not_awaited()
    elif failure == "snapshot":
        assert "snapshot storage unavailable" in result["error"]
        assert result["handoff_snapshot"] is None
        runtime.capture_snapshot.assert_awaited_once()
    else:
        assert result["handoff_snapshot"]["browser_session_id"] == "test-session"
        runtime.capture_snapshot.assert_awaited_once()
