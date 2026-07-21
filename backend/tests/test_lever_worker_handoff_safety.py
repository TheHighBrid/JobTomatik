from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import ats_flow, browser_handoff
from app.services.ats_flow import run_ats_application_flow
from app.services.handoff_confirmation_target import (
    install_handoff_confirmation_target_support,
)
from app.services.supervised_runtime import (
    current_supervised_target,
    supervised_target_scope,
)
from app.services.supervised_target_identity import verify_supervised_browser_target


POSTING_ID = "12345678-1234-1234-1234-123456789abc"
OTHER_POSTING_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
LEVER_URL = f"https://jobs.lever.co/safeco/{POSTING_ID}/apply"
OTHER_LEVER_URL = f"https://jobs.lever.co/safeco/{OTHER_POSTING_ID}/apply"
CONFIRMATION_URL = "https://jobs.lever.co/safeco/thank-you"


def _expected_target():
    return {
        "platform": "lever",
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "verified": True,
        "blockers": [],
        "canonical_application_url": LEVER_URL,
        "site": "safeco",
        "posting_id": POSTING_ID,
        "region": "global",
        "posting_metadata_hash": "a" * 64,
        "identity_hash": "b" * 64,
    }


def _official_payload(*, posting_id=POSTING_ID):
    apply_url = f"https://jobs.lever.co/safeco/{posting_id}/apply"
    return {
        "id": posting_id,
        "text": "Payments Risk Analyst",
        "categories": {"team": "Risk", "location": "Remote"},
        "description": "<p>Risk role</p>",
        "descriptionPlain": "Risk role",
        "hostedUrl": apply_url.removesuffix("/apply"),
        "applyUrl": apply_url,
    }


@pytest.mark.asyncio
async def test_browser_target_verifier_blocks_posting_drift(monkeypatch):
    async def fetch(*args, **kwargs):
        return _official_payload()

    monkeypatch.setattr(
        "app.services.supervised_target_identity.fetch_lever_posting",
        fetch,
    )

    exact = await verify_supervised_browser_target(
        current_url=LEVER_URL,
        adapter_name="lever",
        adapter_version="1.1.0",
        expected_metadata=_expected_target(),
        refresh_official_metadata=False,
    )
    assert exact["verified"] is True

    drifted = await verify_supervised_browser_target(
        current_url=OTHER_LEVER_URL,
        adapter_name="lever",
        adapter_version="1.1.0",
        expected_metadata=_expected_target(),
        refresh_official_metadata=False,
    )
    assert drifted["verified"] is False
    assert "lever_runtime_posting_mismatch" in drifted["blockers"]


@pytest.mark.asyncio
async def test_browser_target_verifier_refreshes_official_metadata(monkeypatch):
    async def changed_metadata(*args, **kwargs):
        payload = _official_payload()
        payload["categories"] = {"team": "Different team", "location": "Remote"}
        return payload

    monkeypatch.setattr(
        "app.services.supervised_target_identity.fetch_lever_posting",
        changed_metadata,
    )

    result = await verify_supervised_browser_target(
        current_url=LEVER_URL,
        adapter_name="lever",
        adapter_version="1.1.0",
        expected_metadata=_expected_target(),
        refresh_official_metadata=True,
    )

    assert result["verified"] is False
    assert "lever_runtime_official_metadata_changed" in result["blockers"]


@pytest.mark.asyncio
async def test_confirmation_route_requires_explicit_same_site_allowance():
    blocked = await verify_supervised_browser_target(
        current_url=CONFIRMATION_URL,
        adapter_name="lever",
        adapter_version="1.1.0",
        expected_metadata=_expected_target(),
        refresh_official_metadata=False,
        allow_same_site_confirmation=False,
    )
    assert blocked["verified"] is False
    assert "lever_runtime_posting_mismatch" in blocked["blockers"]

    allowed = await verify_supervised_browser_target(
        current_url=CONFIRMATION_URL,
        adapter_name="lever",
        adapter_version="1.1.0",
        expected_metadata=_expected_target(),
        refresh_official_metadata=False,
        allow_same_site_confirmation=True,
    )
    assert allowed["verified"] is True
    assert allowed["same_site_confirmation_allowed"] is True


@pytest.mark.asyncio
async def test_handoff_target_verifier_auto_allows_explicit_confirmation(monkeypatch):
    install_handoff_confirmation_target_support()
    page = SimpleNamespace(url=CONFIRMATION_URL)
    session = SimpleNamespace(
        handoff_metadata={"supervised_target": _expected_target()},
    )
    monkeypatch.setattr(
        browser_handoff,
        "_submission_confirmation_state",
        AsyncMock(return_value={
            "submission_confirmed": True,
            "matched_confirmation_phrases": ["thank you for applying"],
        }),
    )
    monkeypatch.setattr(
        browser_handoff,
        "detect_ats_adapter",
        AsyncMock(return_value=SimpleNamespace(name="lever", version="1.1.0")),
    )
    target_verifier = AsyncMock(return_value={
        "verified": True,
        "blockers": [],
        "same_site_confirmation_allowed": True,
    })
    monkeypatch.setattr(
        browser_handoff,
        "verify_supervised_browser_target",
        target_verifier,
    )

    result = await browser_handoff._verify_session_target(page, session)

    assert result["verified"] is True
    assert target_verifier.await_args.kwargs["allow_same_site_confirmation"] is True


def test_supervised_runtime_context_is_scoped_and_reset():
    assert current_supervised_target() is None
    target = _expected_target()

    with supervised_target_scope(target):
        current = current_supervised_target()
        assert current == target
        current["site"] = "mutated-copy"
        assert current_supervised_target()["site"] == "safeco"

    assert current_supervised_target() is None


class _SubmitControl:
    def __init__(self):
        self.clicked = False

    async def click(self):
        self.clicked = True


class _FlowPage:
    def __init__(self):
        self.url = LEVER_URL

    async def wait_for_timeout(self, _milliseconds):
        return None


class _FlowAdapter:
    name = "lever"
    version = "1.1.0"

    def __init__(self, submit):
        self.submit = submit

    async def resolve_surface(self, page):
        return page

    async def prepare(self, surface, log):
        return None

    async def step_fingerprint(self, surface):
        return "fingerprint"

    async def find_submit_button(self, surface):
        return self.submit

    async def find_next_button(self, surface):
        return None

    async def extract_validation_errors(self, surface):
        return []


@pytest.mark.asyncio
async def test_final_submit_is_not_clicked_when_target_check_fails(monkeypatch):
    monkeypatch.setattr(ats_flow, "detect_blocking_challenge", AsyncMock(return_value=None))
    submit = _SubmitControl()
    page = _FlowPage()
    adapter = _FlowAdapter(submit)

    async def fill_step(_surface, _step):
        return {
            "filled_count": 1,
            "review_items": [],
            "control_evidence": [],
            "upload_evidence": [],
        }

    async def pre_submit_check(_page, _adapter):
        return {
            "verified": False,
            "blockers": ["lever_runtime_posting_mismatch"],
        }

    result = await run_ats_application_flow(
        page,
        adapter,
        fill_step=fill_step,
        dry_run=False,
        log=[],
        pre_submit_check=pre_submit_check,
    )

    assert submit.clicked is False
    assert result.success is False
    assert result.requires_manual_review is True
    assert result.review_items[0]["reason_code"] == "safety_gate_blocked"
    assert any(
        event.get("action") == "ats_pre_submit_target_blocked"
        for event in result.step_evidence
    )


@pytest.mark.asyncio
async def test_handoff_action_stops_before_interaction_when_target_drifted(monkeypatch):
    page = SimpleNamespace(
        url=OTHER_LEVER_URL,
        mouse=SimpleNamespace(click=AsyncMock()),
        keyboard=SimpleNamespace(),
    )
    playwright = MagicMock()
    session = SimpleNamespace(
        handoff_metadata={"supervised_target": _expected_target()},
    )

    monkeypatch.setattr(
        browser_handoff,
        "_connect_local_cdp",
        AsyncMock(return_value=(playwright, MagicMock(), MagicMock(), page)),
    )
    monkeypatch.setattr(browser_handoff, "_disconnect", AsyncMock())
    monkeypatch.setattr(
        browser_handoff,
        "_verify_session_target",
        AsyncMock(return_value={
            "verified": False,
            "blockers": ["lever_runtime_posting_mismatch"],
        }),
    )

    with pytest.raises(browser_handoff.BrowserHandoffError):
        await browser_handoff.perform_handoff_action(
            session,
            action="click",
            x=10,
            y=20,
        )

    page.mouse.click.assert_not_awaited()
