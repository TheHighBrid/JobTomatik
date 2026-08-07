from __future__ import annotations

import pytest

from scripts.refresh_android_jobtomatik_tabs import (
    MANAGED_API_URL,
    STALE_SUBMIT_TASK_PREFIX,
    is_jobtomatik_frontend_url,
    normalize_frontend_page,
)


class _FakePage:
    def __init__(self):
        self.evaluate_calls = []
        self.reload_calls = []

    async def evaluate(self, script, payload):
        self.evaluate_calls.append((script, payload))

    async def reload(self, **kwargs):
        self.reload_calls.append(kwargs)


def test_only_local_jobtomatik_frontend_tabs_are_refresh_targets():
    assert is_jobtomatik_frontend_url("http://localhost:3000/applications/31") is True
    assert is_jobtomatik_frontend_url("http://127.0.0.1:3000/search") is True
    assert is_jobtomatik_frontend_url("https://www.linkedin.com/jobs/view/123") is False
    assert is_jobtomatik_frontend_url("http://127.0.0.1:8010/api/system/ready") is False
    assert is_jobtomatik_frontend_url("http://localhost:5173") is False


def test_refresh_targets_authoritative_android_api_and_legacy_task_storage_only():
    assert MANAGED_API_URL == "http://127.0.0.1:8010"
    assert STALE_SUBMIT_TASK_PREFIX == "jobtomatik_submit_task_"


@pytest.mark.asyncio
async def test_refresh_rewrites_api_and_stale_task_storage_before_reloading():
    page = _FakePage()

    await normalize_frontend_page(page)

    assert len(page.evaluate_calls) == 1
    script, payload = page.evaluate_calls[0]
    assert payload == {
        "apiUrl": "http://127.0.0.1:8010",
        "stalePrefix": "jobtomatik_submit_task_",
    }
    assert "localStorage.setItem('jobtomatik_api_url', apiUrl)" in script
    assert "sessionStorage.removeItem(key)" in script
    assert page.reload_calls == [{
        "wait_until": "domcontentloaded",
        "timeout": 20_000,
    }]
