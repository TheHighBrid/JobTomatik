from __future__ import annotations

import pytest

from scripts import refresh_android_jobtomatik_tabs as refresh


class _FakePage:
    def __init__(self, saved_api: str = ""):
        self.saved_api = saved_api
        self.evaluate_calls = []
        self.reload_calls = []

    async def evaluate(self, script, payload):
        self.evaluate_calls.append((script, payload))
        if "localStorage.getItem" in script:
            return self.saved_api
        return None

    async def reload(self, **kwargs):
        self.reload_calls.append(kwargs)


def test_only_local_jobtomatik_frontend_tabs_are_refresh_targets():
    assert refresh.is_jobtomatik_frontend_url("http://localhost:3000/applications/31") is True
    assert refresh.is_jobtomatik_frontend_url("http://127.0.0.1:3000/search") is True
    assert refresh.is_jobtomatik_frontend_url("https://www.linkedin.com/jobs/view/123") is False
    assert refresh.is_jobtomatik_frontend_url("http://127.0.0.1:8010/api/system/ready") is False
    assert refresh.is_jobtomatik_frontend_url("http://localhost:5173") is False


def test_loopback_api_detection_is_narrow():
    assert refresh.is_loopback_api_url("http://127.0.0.1:8011") is True
    assert refresh.is_loopback_api_url("http://localhost:8011") is True
    assert refresh.is_loopback_api_url("http://[::1]:8011") is True
    assert refresh.is_loopback_api_url("https://api.example.com") is False
    assert refresh.is_loopback_api_url("file:///tmp/jobtomatik") is False


def test_refresh_keeps_managed_api_as_default_and_targets_only_legacy_task_storage():
    assert refresh.MANAGED_API_URL == "http://127.0.0.1:8010"
    assert refresh.API_URL_STORAGE_KEY == "jobtomatik_api_url"
    assert refresh.STALE_SUBMIT_TASK_PREFIX == "jobtomatik_submit_task_"


def test_unattested_saved_loopback_api_recovers_only_when_managed_api_is_attested(monkeypatch):
    def fake_attested(url: str, *, timeout: float = 2.0) -> bool:
        return url.rstrip("/") == refresh.MANAGED_API_URL

    monkeypatch.setattr(refresh, "runtime_identity_attested", fake_attested)

    assert refresh.should_recover_saved_api("http://127.0.0.1:8011") is True
    assert refresh.should_recover_saved_api("http://localhost:8012") is True
    assert refresh.should_recover_saved_api(refresh.MANAGED_API_URL) is False
    assert refresh.should_recover_saved_api("https://api.example.com") is False
    assert refresh.should_recover_saved_api("") is False


def test_attested_alternate_loopback_api_is_preserved(monkeypatch):
    monkeypatch.setattr(refresh, "runtime_identity_attested", lambda *args, **kwargs: True)
    assert refresh.should_recover_saved_api("http://127.0.0.1:8011") is False


def test_saved_loopback_api_is_preserved_if_managed_api_is_not_attested(monkeypatch):
    monkeypatch.setattr(refresh, "runtime_identity_attested", lambda *args, **kwargs: False)
    assert refresh.should_recover_saved_api("http://127.0.0.1:8011") is False


@pytest.mark.asyncio
async def test_saved_api_url_reads_operator_selection_from_local_storage():
    page = _FakePage("http://127.0.0.1:8011")
    value = await refresh.saved_api_url(page)
    assert value == "http://127.0.0.1:8011"
    assert len(page.evaluate_calls) == 1
    script, payload = page.evaluate_calls[0]
    assert "localStorage.getItem" in script
    assert payload == {"storageKey": "jobtomatik_api_url"}


@pytest.mark.asyncio
async def test_refresh_preserves_valid_saved_api_and_clears_stale_task_storage_before_reload():
    page = _FakePage()

    await refresh.normalize_frontend_page(page, recover_saved_api=False)

    assert len(page.evaluate_calls) == 1
    script, payload = page.evaluate_calls[0]
    assert payload == {
        "stalePrefix": "jobtomatik_submit_task_",
        "storageKey": "jobtomatik_api_url",
        "managedApiUrl": "http://127.0.0.1:8010",
        "recoverSavedApi": False,
    }
    assert "localStorage.setItem(storageKey, managedApiUrl)" in script
    assert "sessionStorage.removeItem(key)" in script
    assert page.reload_calls == [{
        "wait_until": "domcontentloaded",
        "timeout": 20_000,
    }]


@pytest.mark.asyncio
async def test_refresh_rewrites_only_stale_unattested_saved_api_before_reload():
    page = _FakePage()

    await refresh.normalize_frontend_page(page, recover_saved_api=True)

    _, payload = page.evaluate_calls[0]
    assert payload["recoverSavedApi"] is True
    assert payload["managedApiUrl"] == "http://127.0.0.1:8010"
    assert page.reload_calls == [{
        "wait_until": "domcontentloaded",
        "timeout": 20_000,
    }]
