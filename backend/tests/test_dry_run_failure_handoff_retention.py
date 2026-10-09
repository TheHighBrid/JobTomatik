from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.application import ManualReviewReason
from app.models.handoff import HandoffChallengeType
from app.services import form_filler_handoff, handoff_integration, handoff_session
from app.tasks.applications import _manual_reason_code


class _Evidence:
    present = False

    def as_dict(self):
        return {"present": False}


class _Page:
    def __init__(self):
        self.url = "https://jobs.lever.co/example/posting/apply"

    async def goto(self, *_args, **_kwargs):
        return None

    async def wait_for_load_state(self, *_args, **_kwargs):
        return None


class _Runtime:
    def __init__(self, *, capture_error: bool = False):
        self.page = _Page()
        self.capture_calls = 0
        self.capture_error = capture_error

    async def capture_snapshot(self, *, metadata=None):
        self.capture_calls += 1
        if self.capture_error:
            raise RuntimeError("snapshot unavailable")
        return {
            "browser_provider": "test",
            "browser_session_id": "dry-run-failure-session",
            "current_url": self.page.url,
            "current_fingerprint": "dry-run-failure-fingerprint",
            "metadata": dict(metadata or {}),
        }


def _profile() -> dict:
    return {
        "full_name": "Test Candidate",
        "email": "candidate@example.com",
        "phone": "",
        "address": "",
        "profile_data": {},
        "answer_policies": [],
    }


async def _no_target_id(_page):
    return None


@pytest.mark.asyncio
async def test_failed_dry_run_retains_explicit_automation_error_handoff(monkeypatch):
    runtime = _Runtime()
    release_calls = []

    async def launch(_playwright):
        return runtime

    async def release(_runtime, *, retain_controlled_page=False):
        release_calls.append(retain_controlled_page)

    async def no_entry(_page, _log):
        return {}

    async def generic_adapter(_page, _url):
        return SimpleNamespace(name="generic", version="1.0.0")

    async def no_form(_page):
        return _Evidence()

    async def no_challenge(_page):
        return None

    monkeypatch.setattr(form_filler_handoff, "launch_application_browser", launch)
    monkeypatch.setattr(form_filler_handoff, "release_application_browser", release)
    monkeypatch.setattr(form_filler_handoff, "open_application_entry", no_entry)
    monkeypatch.setattr(form_filler_handoff, "detect_ats_adapter", generic_adapter)
    monkeypatch.setattr(form_filler_handoff, "application_form_evidence", no_form)
    monkeypatch.setattr(form_filler_handoff, "detect_blocking_challenge", no_challenge)
    monkeypatch.setattr(form_filler_handoff, "controlled_page_target_id", _no_target_id)

    result = await form_filler_handoff.fill_and_submit_application_with_handoff(
        job_url=runtime.page.url,
        user_profile=_profile(),
        cover_letter="",
        resume_path="",
        dry_run=True,
    )

    assert result["success"] is False
    assert result["requires_manual_review"] is True
    assert result["handoff_snapshot"]["browser_session_id"] == "dry-run-failure-session"
    assert [item["reason_code"] for item in result["review_items"]] == ["automation_error"]
    assert _manual_reason_code(result, "external_url") == ManualReviewReason.automation_error
    assert runtime.capture_calls == 1
    assert release_calls == [True]

    actions = [item.get("action") for item in result["log"]]
    assert "application_form_not_reached" in actions
    assert "dry_run_failure_handoff_retained" in actions


@pytest.mark.asyncio
async def test_exception_after_browser_launch_is_retained_before_cleanup(monkeypatch):
    runtime = _Runtime()
    release_calls = []

    async def launch(_playwright):
        return runtime

    async def release(_runtime, *, retain_controlled_page=False):
        release_calls.append(retain_controlled_page)

    async def explode(_page, _log):
        raise RuntimeError("ATS flow exploded")

    monkeypatch.setattr(form_filler_handoff, "launch_application_browser", launch)
    monkeypatch.setattr(form_filler_handoff, "release_application_browser", release)
    monkeypatch.setattr(form_filler_handoff, "open_application_entry", explode)
    monkeypatch.setattr(form_filler_handoff, "controlled_page_target_id", _no_target_id)

    result = await form_filler_handoff.fill_and_submit_application_with_handoff(
        job_url=runtime.page.url,
        user_profile=_profile(),
        cover_letter="",
        resume_path="",
        dry_run=True,
    )

    assert result["success"] is False
    assert result["error"] == "ATS flow exploded"
    assert result["handoff_snapshot"]["browser_session_id"] == "dry-run-failure-session"
    assert [item["reason_code"] for item in result["review_items"]] == ["automation_error"]
    assert runtime.capture_calls == 1
    assert release_calls == [True]


@pytest.mark.asyncio
async def test_snapshot_failure_does_not_orphan_browser(monkeypatch):
    runtime = _Runtime(capture_error=True)
    release_calls = []

    async def launch(_playwright):
        return runtime

    async def release(_runtime, *, retain_controlled_page=False):
        release_calls.append(retain_controlled_page)

    async def explode(_page, _log):
        raise RuntimeError("ATS flow exploded")

    monkeypatch.setattr(form_filler_handoff, "launch_application_browser", launch)
    monkeypatch.setattr(form_filler_handoff, "release_application_browser", release)
    monkeypatch.setattr(form_filler_handoff, "open_application_entry", explode)
    monkeypatch.setattr(form_filler_handoff, "controlled_page_target_id", _no_target_id)

    result = await form_filler_handoff.fill_and_submit_application_with_handoff(
        job_url=runtime.page.url,
        user_profile=_profile(),
        cover_letter="",
        resume_path="",
        dry_run=True,
    )

    assert result["success"] is False
    assert result["handoff_snapshot"] is None
    assert runtime.capture_calls == 1
    assert release_calls == [False]
    assert any(
        item.get("action") == "dry_run_failure_handoff_capture_failed"
        for item in result["log"]
    )


def test_automation_error_has_durable_navigation_handoff_route():
    review = SimpleNamespace(reason_code=ManualReviewReason.automation_error.value)
    assert (
        handoff_session.challenge_type_for_review(review)
        == HandoffChallengeType.navigation.value
    )

    result = {
        "review_items": [
            {"reason_code": ManualReviewReason.unsupported_control.value},
            {"reason_code": ManualReviewReason.automation_error.value},
        ]
    }
    assert handoff_integration._handoff_review_reason(
        result,
        ManualReviewReason.unsupported_control,
    ) == ManualReviewReason.automation_error.value
