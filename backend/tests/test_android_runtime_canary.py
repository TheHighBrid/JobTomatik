from __future__ import annotations

from app.tasks.runtime import application_queue_canary


def test_application_queue_canary_reports_revision_pid_redis_db_and_attestation(monkeypatch):
    revision = "abc1234"
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", revision)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", revision)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")

    payload = application_queue_canary.run(expected_revision=revision)

    assert payload["ok"] is True
    assert payload["revision"] == revision
    assert payload["expected_revision"] == revision
    assert isinstance(payload["worker_pid"], int)
    assert payload["redis_db"] is not None
    assert payload["runtime_expected_revision"] == revision
    assert payload["runtime_role"] == "worker"
    assert payload["deployment_attested"] is True
    assert isinstance(payload["runtime_identity_sha256"], str)
    assert len(payload["runtime_identity_sha256"]) == 64


def test_application_queue_canary_rejects_wrong_runtime_revision(monkeypatch):
    actual = "abc1234"
    expected = "def5678"
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", actual)
    monkeypatch.setenv("JOBTOMATIK_EXPECTED_REVISION", actual)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")

    payload = application_queue_canary.run(expected_revision=expected)

    assert payload["ok"] is False
    assert payload["revision"] == actual
    assert payload["deployment_attested"] is True


def test_application_queue_canary_does_not_invent_deployment_attestation(monkeypatch):
    revision = "abc1234"
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_REVISION", revision)
    monkeypatch.delenv("JOBTOMATIK_EXPECTED_REVISION", raising=False)
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")

    payload = application_queue_canary.run(expected_revision=revision)

    assert payload["ok"] is True
    assert payload["runtime_expected_revision"] is None
    assert payload["deployment_attested"] is False
