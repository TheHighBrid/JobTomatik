from __future__ import annotations

from pathlib import Path

import pytest

from scripts import android_runtime_acceptance as acceptance


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class _Result:
    def __init__(self, payload):
        self.payload = payload
        self.forgotten = False

    def get(self, timeout, propagate):
        assert timeout == 15
        assert propagate is True
        return self.payload

    def forget(self):
        self.forgotten = True


class _CanaryTask:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def apply_async(self, *, kwargs, queue):
        self.calls.append({"kwargs": kwargs, "queue": queue})
        return self.result


def _payload(revision: str, worker_pid: int) -> dict:
    return {
        "ok": True,
        "revision": revision,
        "expected_revision": revision,
        "worker_pid": worker_pid,
        "redis_db": 1,
        "runtime_expected_revision": revision,
        "runtime_role": "worker",
        "deployment_attested": True,
        "runtime_identity_sha256": "a" * 64,
    }


def test_worker_acceptance_uses_exact_pid_db1_round_trip_without_remote_inspect(monkeypatch):
    revision = "1" * 40
    worker_pid = 4321
    result = _Result(_payload(revision, worker_pid))
    task = _CanaryTask(result)
    monkeypatch.setattr(acceptance, "application_queue_canary", task)

    proof = acceptance._worker_acceptance(revision, worker_pid)

    assert task.calls == [
        {"kwargs": {"expected_revision": revision}, "queue": "applications"}
    ]
    assert result.forgotten is True
    assert proof["worker_pid"] == worker_pid
    assert proof["declared_queues"] == ["applications", "celery", "followup", "scraping"]
    assert proof["ownership_proof"] == (
        "exact_pid_plus_revision_hostname_plus_queue_cmdline_plus_db1_round_trip"
    )

    source = (BACKEND_ROOT / "scripts/android_runtime_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert "control.inspect" not in source
    assert "active_queues" not in source


def test_worker_acceptance_rejects_canary_consumed_by_different_worker(monkeypatch):
    revision = "2" * 40
    expected_pid = 5001
    result = _Result(_payload(revision, worker_pid=5002))
    monkeypatch.setattr(acceptance, "application_queue_canary", _CanaryTask(result))

    with pytest.raises(RuntimeError, match="different worker PID"):
        acceptance._worker_acceptance(revision, expected_pid)


def test_worker_acceptance_rejects_wrong_runtime_revision(monkeypatch):
    revision = "3" * 40
    worker_pid = 6001
    payload = _payload(revision, worker_pid)
    payload["runtime_expected_revision"] = "4" * 40
    result = _Result(payload)
    monkeypatch.setattr(acceptance, "application_queue_canary", _CanaryTask(result))

    with pytest.raises(RuntimeError, match="expected-revision"):
        acceptance._worker_acceptance(revision, worker_pid)


def test_worker_process_contract_declares_all_required_queues():
    source = (BACKEND_ROOT / "scripts/android_runtime_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert 'REQUIRED_WORKER_QUEUES = "applications,celery,followup,scraping"' in source
    assert '"-Q",\n            REQUIRED_WORKER_QUEUES' in source
