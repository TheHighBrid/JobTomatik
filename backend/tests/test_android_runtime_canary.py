from __future__ import annotations

from app.tasks.runtime import application_queue_canary


def test_application_queue_canary_reports_revision_pid_and_redis_db(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", "abc123")

    payload = application_queue_canary.run(expected_revision="abc123")

    assert payload["ok"] is True
    assert payload["revision"] == "abc123"
    assert payload["expected_revision"] == "abc123"
    assert isinstance(payload["worker_pid"], int)
    assert payload["redis_db"] is not None


def test_application_queue_canary_rejects_wrong_runtime_revision(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", "actual")

    payload = application_queue_canary.run(expected_revision="expected")

    assert payload["ok"] is False
    assert payload["revision"] == "actual"
