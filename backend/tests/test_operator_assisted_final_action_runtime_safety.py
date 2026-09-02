from types import SimpleNamespace

import pytest

from app.models.handoff import HandoffChallengeType, ManualHandoffSession
from app.services import browser_handoff
from app.services import operator_assisted_handoff_integration as integration


LEVER_URL = "https://jobs.lever.co/safeco/posting-123/apply"


def _session(*, live_snapshot_checkpointed: bool = False) -> ManualHandoffSession:
    return ManualHandoffSession(
        application_id=1,
        manual_review_id=1,
        user_id=1,
        challenge_type=HandoffChallengeType.final_submit.value,
        status="claimed",
        idempotency_key="final-action-runtime-safety",
        resume_token_hash="hash",
        encrypted_resume_token="encrypted",
        resume_token_prefix="prefix",
        browser_provider="local_cdp",
        current_url=LEVER_URL,
        current_fingerprint="persisted-before",
        handoff_metadata={
            "operator_submit_pre_submit_url": "https://jobs.lever.co/safeco/stale/apply",
            "operator_submit_pre_submit_fingerprint": "stale-before",
            "operator_submit_live_snapshot_checkpointed": live_snapshot_checkpointed,
            "operator_submit_confirmation_observed": False,
            "automatic_retry_allowed": False,
            "supervised_target": {
                "adapter": "lever",
                "adapter_version": "1.1.0",
            },
        },
    )


@pytest.mark.parametrize(
    ("operations", "core", "expected"),
    [
        (
            SimpleNamespace(
                global_kill_switch=True,
                autopilot_enabled=False,
                disabled_platforms="",
            ),
            SimpleNamespace(
                allow_real_application_submit=False,
                lever_supervised_pilot_enabled=False,
            ),
            "global_kill_switch_active",
        ),
        (
            SimpleNamespace(
                global_kill_switch=False,
                autopilot_enabled=True,
                disabled_platforms="",
            ),
            SimpleNamespace(
                allow_real_application_submit=False,
                lever_supervised_pilot_enabled=False,
            ),
            "operator_assisted_requires_autopilot_disabled",
        ),
        (
            SimpleNamespace(
                global_kill_switch=False,
                autopilot_enabled=False,
                disabled_platforms="",
            ),
            SimpleNamespace(
                allow_real_application_submit=True,
                lever_supervised_pilot_enabled=False,
            ),
            "operator_assisted_requires_global_submit_disabled",
        ),
        (
            SimpleNamespace(
                global_kill_switch=False,
                autopilot_enabled=False,
                disabled_platforms="",
            ),
            SimpleNamespace(
                allow_real_application_submit=False,
                lever_supervised_pilot_enabled=True,
            ),
            "operator_assisted_requires_platform_pilot_disabled",
        ),
        (
            SimpleNamespace(
                global_kill_switch=False,
                autopilot_enabled=False,
                disabled_platforms="lever",
            ),
            SimpleNamespace(
                allow_real_application_submit=False,
                lever_supervised_pilot_enabled=False,
            ),
            "platform_disabled",
        ),
    ],
)
def test_operator_final_action_runtime_blockers_fail_closed(
    monkeypatch,
    operations,
    core,
    expected,
):
    monkeypatch.setattr(integration, "get_operations_settings", lambda: operations)
    monkeypatch.setattr(integration, "get_settings", lambda: core)

    blockers = integration._operator_final_action_blockers(LEVER_URL)

    assert expected in blockers


@pytest.mark.asyncio
async def test_global_kill_switch_blocks_before_browser_connection(monkeypatch):
    integration.install_operator_assisted_handoff_integration()
    monkeypatch.setattr(
        integration,
        "get_operations_settings",
        lambda: SimpleNamespace(
            global_kill_switch=True,
            autopilot_enabled=False,
            disabled_platforms="",
        ),
    )
    monkeypatch.setattr(
        integration,
        "get_settings",
        lambda: SimpleNamespace(
            allow_real_application_submit=False,
            lever_supervised_pilot_enabled=False,
        ),
    )
    connected = []

    async def should_not_connect(_session):
        connected.append(True)
        raise AssertionError("browser connection must not start under emergency stop")

    monkeypatch.setattr(browser_handoff, "_connect_local_cdp", should_not_connect)

    with pytest.raises(browser_handoff.BrowserHandoffError, match="global_kill_switch_active"):
        await browser_handoff.perform_handoff_action(
            _session(),
            action="operator_submit",
        )

    assert connected == []


@pytest.mark.asyncio
async def test_runtime_gate_drift_after_checkpoint_blocks_before_click(monkeypatch):
    integration.install_operator_assisted_handoff_integration()
    session = _session()
    events = []
    blocker_calls = []

    def blockers(_url):
        blocker_calls.append(len(blocker_calls) + 1)
        if len(blocker_calls) >= 3:
            return ["global_kill_switch_active"]
        return []

    monkeypatch.setattr(integration, "_operator_final_action_blockers", blockers)

    class Page:
        url = LEVER_URL

        async def wait_for_timeout(self, _milliseconds):
            return None

    page = Page()

    class Control:
        async def is_visible(self):
            return True

        async def is_enabled(self):
            return True

        async def click(self):
            events.append("click")

    control = Control()

    class Adapter:
        name = "lever"
        version = "1.1.0"

        async def resolve_surface(self, _page):
            return object()

        async def step_fingerprint(self, _surface):
            return "lever-step-before"

        async def find_submit_button(self, _surface):
            return control

        async def extract_validation_errors(self, _surface):
            return []

        async def detect_confirmation(self, _surface, **_kwargs):
            return []

    async def connect(_session):
        return object(), None, None, page

    async def verify(_page, _session, **_kwargs):
        return {"verified": True, "blockers": []}

    async def detect(_page, _url):
        return Adapter()

    async def disconnect(_playwright):
        return None

    async def page_fingerprint(_page):
        return "fresh-live-before"

    monkeypatch.setattr(browser_handoff, "_connect_local_cdp", connect)
    monkeypatch.setattr(browser_handoff, "_verify_session_target", verify)
    monkeypatch.setattr(browser_handoff, "_require_verified_session_target", lambda _value: None)
    monkeypatch.setattr(browser_handoff, "detect_ats_adapter", detect)
    monkeypatch.setattr(browser_handoff, "page_fingerprint", page_fingerprint)
    monkeypatch.setattr(
        browser_handoff,
        "_session_supervised_target",
        lambda _session: {"adapter": "lever", "adapter_version": "1.1.0"},
    )
    monkeypatch.setattr(browser_handoff, "_disconnect", disconnect)

    def checkpoint(_session, *, current_url, current_fingerprint):
        events.append("checkpoint")
        assert current_url == LEVER_URL
        assert current_fingerprint == "fresh-live-before"
        _session.current_url = current_url
        _session.current_fingerprint = current_fingerprint
        _session.handoff_metadata = {
            **dict(_session.handoff_metadata or {}),
            "operator_submit_live_snapshot_checkpointed": True,
            "operator_submit_pre_submit_url": current_url,
            "operator_submit_pre_submit_fingerprint": current_fingerprint,
        }

    monkeypatch.setattr(integration, "_checkpoint_fresh_live_snapshot", checkpoint)

    with pytest.raises(browser_handoff.BrowserHandoffError, match="global_kill_switch_active"):
        await browser_handoff.perform_handoff_action(
            session,
            action="operator_submit",
        )

    assert events == ["checkpoint"]
    assert blocker_calls == [1, 2, 3]


@pytest.mark.asyncio
async def test_stale_uncheckpointed_url_cannot_strengthen_confirmation(monkeypatch):
    integration.install_operator_assisted_handoff_integration()

    async def generic_transition(_session):
        return browser_handoff.BrowserVerification(
            challenge_cleared=True,
            provider="local_cdp",
            current_url="https://jobs.lever.co/safeco/thank-you",
            current_fingerprint="after-submit",
            evidence={
                "submission_confirmed": True,
                "confirmation_url_signal": True,
                "target_verification": {"verified": True, "blockers": []},
                "verification_method": "explicit_submission_confirmation",
            },
        )

    monkeypatch.setattr(integration, "_ORIGINAL_VERIFY_COMPLETION", generic_transition)
    result = await browser_handoff.verify_browser_handoff_completion(
        _session(live_snapshot_checkpointed=False)
    )

    assert result.challenge_cleared is False
    assert result.evidence["submission_confirmed"] is False
    assert result.evidence["operator_submit_live_snapshot_checkpointed"] is False
    assert result.evidence["provable_confirmation_transition"] is False


@pytest.mark.asyncio
async def test_fresh_checkpoint_is_required_for_confirmation_transition_fallback(monkeypatch):
    integration.install_operator_assisted_handoff_integration()

    async def generic_transition(_session):
        return browser_handoff.BrowserVerification(
            challenge_cleared=True,
            provider="local_cdp",
            current_url="https://jobs.lever.co/safeco/thank-you",
            current_fingerprint="after-submit",
            evidence={
                "submission_confirmed": True,
                "confirmation_url_signal": True,
                "target_verification": {"verified": True, "blockers": []},
                "verification_method": "explicit_submission_confirmation",
            },
        )

    session = _session(live_snapshot_checkpointed=True)
    session.handoff_metadata["operator_submit_pre_submit_url"] = LEVER_URL
    monkeypatch.setattr(integration, "_ORIGINAL_VERIFY_COMPLETION", generic_transition)
    result = await browser_handoff.verify_browser_handoff_completion(session)

    assert result.challenge_cleared is True
    assert result.evidence["submission_confirmed"] is True
    assert result.evidence["operator_submit_live_snapshot_checkpointed"] is True
    assert result.evidence["provable_confirmation_transition"] is True
