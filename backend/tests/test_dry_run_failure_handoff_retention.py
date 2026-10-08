from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import form_filler_handoff


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
    def __init__(self):
        self.page = _Page()
        self.capture_calls = 0

    async def capture_snapshot(self, *, metadata=None):
        self.capture_calls += 1
        return {
            "browser_provider": "test",
            "browser_session_id": "dry-run-failure-session",
            "current_url": self.page.url,
            "current_fingerprint": "dry-run-failure-fingerprint",
            "metadata": dict(metadata or {}),
        }


@pytest.mark.asyncio
async def test_failed_dry_run_retains_browser_for_diagnostics(monkeypatch):
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

    async def no_target_id(_page):
        return None

    monkeypatch.setattr(form_filler_handoff, "launch_application_browser", launch)
    monkeypatch.setattr(form_filler_handoff, "release_application_browser", release)
    monkeypatch.setattr(form_filler_handoff, "open_application_entry", no_entry)
    monkeypatch.setattr(form_filler_handoff, "detect_ats_adapter", generic_adapter)
    monkeypatch.setattr(form_filler_handoff, "application_form_evidence", no_form)
    monkeypatch.setattr(form_filler_handoff, "detect_blocking_challenge", no_challenge)
    monkeypatch.setattr(form_filler_handoff, "controlled_page_target_id", no_target_id)

    result = await form_filler_handoff.fill_and_submit_application_with_handoff(
        job_url=runtime.page.url,
        user_profile={
            "full_name": "Test Candidate",
            "email": "candidate@example.com",
            "phone": "",
            "address": "",
            "profile_data": {},
            "answer_policies": [],
        },
        cover_letter="",
        resume_path="",
        dry_run=True,
    )

    assert result["success"] is False
    assert result["requires_manual_review"] is True
    assert result["handoff_snapshot"]["browser_session_id"] == "dry-run-failure-session"
    assert runtime.capture_calls == 1
    assert release_calls == [True]

    actions = [item.get("action") for item in result["log"]]
    assert "application_form_not_reached" in actions
    assert "dry_run_failure_handoff_retained" in actions
