from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts import certify_lever_live as live


class _FakePage:
    url = "https://jobs.lever.co/example/dead-posting/apply"

    async def title(self) -> str:
        return "Not found - 404 error"

    async def close(self) -> None:
        return None


class _FakeSurface:
    url = _FakePage.url


class _FakeAdapter:
    name = "lever"
    version = "1.1.0"

    async def find_next_button(self, _surface):
        return None

    async def find_submit_button(self, _surface):
        return None


class _FakeBrowser:
    async def close(self) -> None:
        return None


class _FakeChromium:
    async def launch(self, **_kwargs):
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()


class _FakePlaywrightManager:
    async def __aenter__(self):
        return _FakePlaywright()

    async def __aexit__(self, _exc_type, _exc, _tb):
        return False


def _not_found_error() -> httpx.HTTPStatusError:
    request = httpx.Request(
        "GET",
        "https://api.lever.co/v0/postings/example/dead-posting?mode=json",
    )
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError(
        "posting not found",
        request=request,
        response=response,
    )


@pytest.mark.asyncio
async def test_inspection_classifies_official_404_as_posting_unavailable(monkeypatch):
    async def fake_load(_url, _browser):
        return _FakePage(), _FakeAdapter(), _FakeSurface(), []

    async def fake_inventory(_surface):
        return {
            "controls": [],
            "visible_control_count": 0,
            "required_control_count": 0,
            "required_custom_controls": [],
            "final_submit_clicked": False,
        }

    async def fake_fetch(*_args, **_kwargs):
        raise _not_found_error()

    monkeypatch.setattr(live, "_load_application_surface", fake_load)
    monkeypatch.setattr(live, "inspect_lever_application_dom", fake_inventory)
    monkeypatch.setattr(live, "fetch_lever_posting", fake_fetch)

    report = await live.inspect_live_url(_FakePage.url, object())

    assert report["passed"] is False
    assert report["posting_available"] is False
    assert report["posting_http_status"] == 404
    assert report["availability_reason_code"] == "posting_unavailable"
    assert report["final_submit_clicked"] is False
    assert "official Postings API" in report["error"]


def test_unavailable_exercise_report_is_nonqualifying_and_never_submits():
    report = live._posting_unavailable_exercise_report(
        _FakePage.url,
        {
            "adapter": "lever",
            "adapter_version": "1.1.0",
            "site": "example",
            "posting_id": "dead-posting",
            "region": "global",
            "posting_available": False,
            "posting_http_status": 404,
        },
    )

    assert report["passed"] is False
    assert report["certification_outcome"] == "posting_unavailable"
    assert report["exercise_skipped"] is True
    assert report["ready_to_submit"] is False
    assert report["requires_manual_review"] is False
    assert report["fields_filled"] == 0
    assert report["final_submit_clicked"] is False
    assert report["review_items"][0]["reason_code"] == "posting_unavailable"


@pytest.mark.asyncio
async def test_main_skips_profile_build_and_form_exercise_for_unavailable_posting(
    monkeypatch,
    tmp_path: Path,
):
    async def fake_inspection(url, _browser):
        return {
            "url": url,
            "mode": "inspect",
            "passed": False,
            "final_submit_clicked": False,
            "posting_available": False,
            "posting_http_status": 410,
            "availability_reason_code": "posting_unavailable",
            "adapter": "lever",
            "adapter_version": "1.1.0",
            "site": "example",
            "posting_id": "expired-posting",
            "region": "global",
            "error": "The posting is unavailable.",
        }

    async def should_not_build_profile(*_args, **_kwargs):
        raise AssertionError("Unavailable postings must not open a second exercise browser")

    monkeypatch.setattr(
        "playwright.async_api.async_playwright",
        lambda: _FakePlaywrightManager(),
    )
    monkeypatch.setattr(live, "inspect_live_url", fake_inspection)
    monkeypatch.setattr(live, "_build_profile_for_url", should_not_build_profile)
    monkeypatch.setattr(
        live,
        "write_synthetic_resume",
        lambda target: Path(target).write_bytes(b"synthetic"),
    )

    output = tmp_path / "report.json"
    resume = tmp_path / "resume.pdf"
    args = SimpleNamespace(
        urls="https://jobs.lever.co/example/expired-posting/apply",
        exercise=True,
        synthetic_resume_path=str(resume),
        report=str(output),
    )

    status = await live.main_async(args)
    payload = json.loads(output.read_text(encoding="utf-8"))
    exercises = [item for item in payload["reports"] if item["mode"] == "exercise"]

    assert status == 1
    assert payload["passed"] is False
    assert payload["final_submit_clicked"] is False
    assert len(exercises) == 1
    assert exercises[0]["certification_outcome"] == "posting_unavailable"
    assert exercises[0]["exercise_skipped"] is True
