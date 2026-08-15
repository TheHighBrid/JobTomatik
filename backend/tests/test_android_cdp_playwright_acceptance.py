from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import browser_runtime
from scripts import android_runtime_acceptance as acceptance
from scripts import run_shadow_qualification_canary as qualification


class _SuccessfulChromium:
    def __init__(self):
        self.timeouts: list[int] = []

    async def connect_over_cdp(self, endpoint, timeout):
        assert endpoint == "http://127.0.0.1:9222"
        self.timeouts.append(int(timeout))
        return object()


@pytest.mark.asyncio
async def test_external_android_cdp_attach_is_not_restarted_every_ten_seconds():
    chromium = _SuccessfulChromium()
    playwright = SimpleNamespace(chromium=chromium)

    result = await browser_runtime._connect_external_playwright_over_cdp(
        playwright,
        "http://127.0.0.1:9222",
    )

    assert result is not None
    assert chromium.timeouts
    assert chromium.timeouts[0] > 10_000
    assert chromium.timeouts[0] <= 45_000
    assert browser_runtime.EXTERNAL_CDP_CONNECT_TIMEOUT_SECONDS >= 60


def test_android_acceptance_requires_real_playwright_attachment(monkeypatch):
    monkeypatch.setattr(
        acceptance,
        "_backend_settings",
        lambda: SimpleNamespace(application_browser_cdp_endpoint=""),
    )
    monkeypatch.setattr(
        acceptance,
        "get_settings",
        lambda: SimpleNamespace(application_browser_cdp_endpoint="http://127.0.0.1:9222"),
    )
    calls = []

    async def fake_probe(endpoint):
        calls.append(endpoint)
        return {
            "playwright_attach_ready": True,
            "cdp_endpoint": endpoint,
            "context_count": 1,
            "page_count": 1,
            "current_url": "https://www.linkedin.com/feed/",
            "browser_owned_by_jobtomatik": False,
        }

    monkeypatch.setattr(acceptance, "probe_external_playwright_cdp", fake_probe)

    proof = acceptance._playwright_browser_acceptance()

    assert calls == ["http://127.0.0.1:9222"]
    assert proof["playwright_attach_ready"] is True
    assert proof["browser_owned_by_jobtomatik"] is False


def test_android_acceptance_rejects_missing_playwright_attachment(monkeypatch):
    monkeypatch.setattr(
        acceptance,
        "_backend_settings",
        lambda: SimpleNamespace(application_browser_cdp_endpoint=""),
    )
    monkeypatch.setattr(
        acceptance,
        "get_settings",
        lambda: SimpleNamespace(application_browser_cdp_endpoint="http://127.0.0.1:9222"),
    )

    async def fake_probe(_endpoint):
        return {
            "playwright_attach_ready": False,
            "browser_owned_by_jobtomatik": False,
        }

    monkeypatch.setattr(acceptance, "probe_external_playwright_cdp", fake_probe)

    with pytest.raises(RuntimeError, match="did not pass Playwright CDP attachment"):
        acceptance._playwright_browser_acceptance()


def test_android_acceptance_loads_cdp_endpoint_from_backend_env(monkeypatch, tmp_path):
    backend_root = tmp_path / "backend"
    backend_root.mkdir()
    (backend_root / ".env").write_text(
        "APPLICATION_BROWSER_CDP_ENDPOINT=http://127.0.0.1:9222\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(acceptance, "BACKEND_ROOT", backend_root)
    monkeypatch.delenv("APPLICATION_BROWSER_CDP_ENDPOINT", raising=False)
    monkeypatch.setattr(
        acceptance,
        "get_settings",
        lambda: SimpleNamespace(application_browser_cdp_endpoint=""),
    )

    assert acceptance._configured_browser_cdp_endpoint() == "http://127.0.0.1:9222"


def test_android_acceptance_rejects_process_cdp_mismatch(monkeypatch, tmp_path):
    backend_root = tmp_path / "backend"
    backend_root.mkdir()
    (backend_root / ".env").write_text(
        "APPLICATION_BROWSER_CDP_ENDPOINT=http://127.0.0.1:9222\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(acceptance, "BACKEND_ROOT", backend_root)
    monkeypatch.setenv("APPLICATION_BROWSER_CDP_ENDPOINT", "http://127.0.0.1:9333")

    with pytest.raises(RuntimeError, match="differs from managed backend runtime config"):
        acceptance._configured_browser_cdp_endpoint()


def test_android_acceptance_base_uses_backend_runtime_settings(monkeypatch):
    authoritative = SimpleNamespace(
        application_browser_cdp_endpoint="http://127.0.0.1:9222",
        allow_real_application_submit=True,
        allow_real_followup_send=False,
    )
    observed = {}

    monkeypatch.setattr(acceptance, "_backend_settings", lambda: authoritative)
    monkeypatch.setattr(
        acceptance,
        "_playwright_browser_acceptance",
        lambda: {"playwright_attach_ready": True, "browser_owned_by_jobtomatik": False},
    )

    def fake_base_run_acceptance():
        observed["settings"] = acceptance._base.get_settings()
        return {"browser": {}}

    monkeypatch.setattr(acceptance._base, "run_acceptance", fake_base_run_acceptance)

    acceptance.run_acceptance()

    assert observed["settings"] is authoritative
    assert acceptance._base.get_settings is not acceptance._backend_settings


class _NoQueryDB:
    def expire_all(self):
        return None

    def query(self, *_args, **_kwargs):
        raise AssertionError("terminal worker failure must be raised before session polling")


def test_qualification_worker_failure_is_immediate_not_eight_minute_timeout(monkeypatch):
    snapshot = {
        "application_id": 53,
        "automation_state": "failed",
        "submission_attempt_count": 1,
        "browser_or_form_path_observed": False,
        "safe_terminal": False,
        "consequential_state_observed": False,
        "worker_failure_error": "Playwright could not attach to Android/native Chromium",
        "worker_failure_event_payload": {
            "method": "external_url",
            "error": "Playwright could not attach to Android/native Chromium",
        },
    }
    monkeypatch.setattr(
        qualification,
        "_application_snapshot",
        lambda _db, _application_id: dict(snapshot),
    )

    with pytest.raises(RuntimeError, match="Canary worker application failed") as exc_info:
        qualification._wait_for_application_path(
            _NoQueryDB(),
            application_id=53,
            session_id=99,
            timeout_seconds=8 * 60,
        )

    message = str(exc_info.value)
    assert "Playwright could not attach" in message
    assert '"application_id": 53' in message
