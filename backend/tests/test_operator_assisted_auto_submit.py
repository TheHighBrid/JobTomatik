from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

from app.models.application import ManualReviewReason
from app.services import operator_assisted_auto_submit as auto_submit
from app.tasks import operator_assisted


def _final_boundary_result():
    return {
        "handoff_public_id": "handoff-1",
        "requires_manual_review": True,
        "review_items": [
            {
                "reason_code": ManualReviewReason.operator_final_submit_required.value,
            }
        ],
    }


def test_operator_prepare_defaults_to_one_shot_auto_final_submit():
    signature = inspect.signature(operator_assisted.prepare_operator_assisted_application_task.run)
    assert signature.parameters["auto_final_submit"].default is True


def test_only_final_submit_boundary_enters_auto_final_layer():
    assert operator_assisted._is_final_submit_boundary(_final_boundary_result()) is True

    question = {
        "handoff_public_id": "question-handoff",
        "requires_manual_review": True,
        "review_items": [{"reason_code": ManualReviewReason.ambiguous_question.value}],
    }
    captcha = {
        "handoff_public_id": "captcha-handoff",
        "requires_manual_review": True,
        "review_items": [{"reason_code": ManualReviewReason.captcha_detected.value}],
    }
    assert operator_assisted._is_final_submit_boundary(question) is False
    assert operator_assisted._is_final_submit_boundary(captcha) is False


def test_authorization_snapshot_binds_exact_payload_and_target():
    preflight = {
        "application_id": 298,
        "employer": "Flex",
        "role": "Example Role",
        "application_url": "https://jobs.lever.co/flex/posting/apply",
        "combined_payload_hash": "a" * 64,
        "target_identity_hash": "b" * 64,
    }
    snapshot = auto_submit.authorization_snapshot(preflight, task_id="task-298")

    assert snapshot["authorization_source"] == "authenticated_operator_prepare_request"
    assert snapshot["task_id"] == "task-298"
    for field in auto_submit._AUTH_FIELDS:
        assert snapshot[field] == preflight[field]

    unchanged = dict(preflight)
    assert auto_submit._authorization_drift(unchanged, snapshot) == []
    changed = {**preflight, "combined_payload_hash": "c" * 64}
    assert auto_submit._authorization_drift(changed, snapshot) == ["combined_payload_hash"]


def test_manual_boundary_never_claims_a_retry():
    result = auto_submit._manual_boundary_result(
        handoff_public_id="handoff-1",
        blocker="captcha_or_passive_verification",
        reason="Human verification required",
    )
    assert result["requires_manual_review"] is True
    assert result["final_submit_clicked_by_jobtomatik"] is False
    assert result["automatic_retry_allowed"] is False


def test_precheck_stops_before_submit_when_passive_verification_is_present(monkeypatch):
    disconnected = []
    page = SimpleNamespace(url="https://jobs.lever.co/flex/posting/apply")
    session = SimpleNamespace(public_id="handoff-1")
    playwright = object()

    async def connect(_session):
        return playwright, object(), object(), page

    async def disconnect(value):
        disconnected.append(value)

    async def verification_state(_page):
        return {"captcha_present": True}

    monkeypatch.setattr(auto_submit.browser_handoff_service, "_connect_local_cdp", connect)
    monkeypatch.setattr(auto_submit.browser_handoff_service, "_disconnect", disconnect)

    from app.services import operator_assisted_live_pilot_hardening as hardening

    monkeypatch.setattr(hardening, "passive_verification_state", verification_state)
    monkeypatch.setattr(
        hardening,
        "passive_verification_requires_manual_browser",
        lambda _state: True,
    )

    result = asyncio.run(auto_submit._precheck_retained_lever_page(session))
    assert result["ready"] is False
    assert result["blocker"] == "captcha_or_passive_verification"
    assert disconnected == [playwright]


def test_precheck_requires_exact_visible_enabled_lever_submit(monkeypatch):
    page = SimpleNamespace(url="https://jobs.lever.co/flex/posting/apply")
    session = SimpleNamespace(public_id="handoff-1")

    class SubmitControl:
        async def is_visible(self):
            return True

        async def is_enabled(self):
            return True

    class Adapter:
        name = "lever"
        version = "1.1.0"

        async def resolve_surface(self, _page):
            return object()

        async def extract_validation_errors(self, _surface):
            return []

        async def find_submit_button(self, _surface):
            return SubmitControl()

    async def connect(_session):
        return object(), object(), object(), page

    async def disconnect(_playwright):
        return None

    async def verify(_page, _session):
        return {"verified": True, "blockers": []}

    async def detect(_page, _url):
        return Adapter()

    async def verification_state(_page):
        return {"captcha_present": False}

    monkeypatch.setattr(auto_submit.browser_handoff_service, "_connect_local_cdp", connect)
    monkeypatch.setattr(auto_submit.browser_handoff_service, "_disconnect", disconnect)
    monkeypatch.setattr(auto_submit.browser_handoff_service, "_verify_session_target", verify)
    monkeypatch.setattr(auto_submit.browser_handoff_service, "_require_verified_session_target", lambda value: None)
    monkeypatch.setattr(auto_submit.browser_handoff_service, "detect_ats_adapter", detect)
    monkeypatch.setattr(
        auto_submit.browser_handoff_service,
        "_session_supervised_target",
        lambda _session: {"adapter": "lever", "adapter_version": "1.1.0"},
    )

    from app.services import operator_assisted_live_pilot_hardening as hardening

    monkeypatch.setattr(hardening, "passive_verification_state", verification_state)
    monkeypatch.setattr(
        hardening,
        "passive_verification_requires_manual_browser",
        lambda _state: False,
    )

    result = asyncio.run(auto_submit._precheck_retained_lever_page(session))
    assert result["ready"] is True
    assert result["current_url"] == page.url
