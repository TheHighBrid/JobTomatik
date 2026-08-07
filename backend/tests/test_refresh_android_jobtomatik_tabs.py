from __future__ import annotations

from scripts.refresh_android_jobtomatik_tabs import (
    MANAGED_API_URL,
    STALE_SUBMIT_TASK_PREFIX,
    is_jobtomatik_frontend_url,
)


def test_only_local_jobtomatik_frontend_tabs_are_refresh_targets():
    assert is_jobtomatik_frontend_url("http://localhost:3000/applications/31") is True
    assert is_jobtomatik_frontend_url("http://127.0.0.1:3000/search") is True
    assert is_jobtomatik_frontend_url("https://www.linkedin.com/jobs/view/123") is False
    assert is_jobtomatik_frontend_url("http://127.0.0.1:8010/api/system/ready") is False
    assert is_jobtomatik_frontend_url("http://localhost:5173") is False


def test_refresh_targets_authoritative_android_api_and_legacy_task_storage_only():
    assert MANAGED_API_URL == "http://127.0.0.1:8010"
    assert STALE_SUBMIT_TASK_PREFIX == "jobtomatik_submit_task_"
