from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from scripts import android_runtime_acceptance as acceptance


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class _Result:
    def __init__(self, payload):
        self.payload = payload
        self.forgotten = False
        self.ready_calls = 0

    def ready(self):
        self.ready_calls += 1
        return True

    def get(self, timeout, propagate):
        assert timeout == 5
        assert propagate is True
        return self.payload

    def forget(self):
        self.forgotten = True


class _DelayedResult(_Result):
    def __init__(self, payload, *, ready_after: int):
        super().__init__(payload)
        self.ready_after = int(ready_after)

    def ready(self):
        self.ready_calls += 1
        return self.ready_calls >= self.ready_after


class _NeverReadyResult(_Result):
    def ready(self):
        self.ready_calls += 1
        return False


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
    assert result.ready_calls == 1
    assert proof["worker_pid"] == worker_pid
    assert proof["declared_queues"] == ["applications", "celery", "followup", "scraping"]
    assert proof["queue_wait_seconds"] >= 0
    assert proof["ownership_proof"] == (
        "exact_pid_plus_revision_hostname_plus_queue_cmdline_plus_db1_round_trip"
    )

    function_source = inspect.getsource(acceptance._worker_acceptance)
    assert "celery_app.control.inspect" not in function_source
    assert "application_queue_canary.apply_async" in function_source
    assert "result.ready()" in function_source


def test_worker_acceptance_waits_through_transient_solo_worker_queue_contention(monkeypatch):
    revision = "5" * 40
    worker_pid = 7001
    result = _DelayedResult(_payload(revision, worker_pid), ready_after=4)
    task = _CanaryTask(result)
    identity_checks = []

    monkeypatch.setattr(acceptance, "application_queue_canary", task)
    monkeypatch.setattr(acceptance.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        acceptance,
        "_assert_tokens",
        lambda label, pid, *tokens: identity_checks.append((label, pid, tokens)) or {"pid": pid},
    )

    proof = acceptance._worker_acceptance(revision, worker_pid)

    assert result.ready_calls == 4
    assert len(identity_checks) == 3
    assert all(item[0] == "worker" and item[1] == worker_pid for item in identity_checks)
    assert task.calls == [
        {"kwargs": {"expected_revision": revision}, "queue": "applications"}
    ]
    assert result.forgotten is True
    assert proof["queue_canary"]["worker_pid"] == worker_pid


def test_worker_acceptance_fails_boundedly_if_same_canary_never_completes(monkeypatch):
    revision = "6" * 40
    worker_pid = 8001
    result = _NeverReadyResult(_payload(revision, worker_pid))
    task = _CanaryTask(result)
    clock = iter([10.0, 10.0 + acceptance.WORKER_CANARY_MAX_WAIT_SECONDS + 1.0])

    monkeypatch.setattr(acceptance, "application_queue_canary", task)
    monkeypatch.setattr(acceptance.time, "monotonic", lambda: next(clock))

    with pytest.raises(RuntimeError, match="did not complete within 180 seconds"):
        acceptance._worker_acceptance(revision, worker_pid)

    assert result.forgotten is True
    assert task.calls == [
        {"kwargs": {"expected_revision": revision}, "queue": "applications"}
    ]


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
    assert "def _worker_identity_tokens" in source
    assert '"-Q",' in source
    assert "REQUIRED_WORKER_QUEUES," in source
