from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from scripts import android_runtime_acceptance as acceptance


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _receipt(revision: str, worker_pid: int) -> dict:
    queue_canary = {
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
    return {
        "version": 1,
        "status": "pass",
        "revision": revision,
        "expected_revision": revision,
        "redis_db": 1,
        "worker_pid": worker_pid,
        "worker_start_token": "12345",
        "runtime_role": "worker",
        "deployment_attested": True,
        "runtime_identity_sha256": "a" * 64,
        "declared_queues": ["applications", "celery", "followup", "scraping"],
        "queue_canary": queue_canary,
        "proof": "startup_exact_worker_db1_round_trip",
    }


def test_worker_acceptance_uses_startup_receipt_without_dispatching_duplicate_canary(monkeypatch, tmp_path):
    revision = "1" * 40
    worker_pid = 4321
    receipt = _receipt(revision, worker_pid)
    calls = []

    def validate(path, *, expected_revision, expected_worker_pid, required_queues):
        calls.append(
            {
                "path": path,
                "expected_revision": expected_revision,
                "expected_worker_pid": expected_worker_pid,
                "required_queues": list(required_queues),
            }
        )
        return {
            "ok": True,
            "blockers": [],
            "receipt": receipt,
            "worker_start_token": "12345",
        }

    monkeypatch.setattr(acceptance, "validate_worker_canary_receipt", validate)

    proof = acceptance._worker_acceptance(revision, worker_pid, directory=tmp_path)

    assert calls == [
        {
            "path": tmp_path / "celery-application-canary.json",
            "expected_revision": revision,
            "expected_worker_pid": worker_pid,
            "required_queues": ["applications", "celery", "followup", "scraping"],
        }
    ]
    assert proof["worker_pid"] == worker_pid
    assert proof["worker_start_token"] == "12345"
    assert proof["queue_canary"]["redis_db"] == 1
    assert proof["startup_canary_receipt"] == receipt
    assert proof["ownership_proof"] == (
        "exact_pid_plus_process_start_token_plus_revision_hostname_plus_queue_cmdline_"
        "plus_startup_db1_round_trip_receipt"
    )

    function_source = inspect.getsource(acceptance._worker_acceptance)
    assert "celery_app.control.inspect" not in function_source
    assert "application_queue_canary.apply_async" not in function_source
    assert "result.ready()" not in function_source
    assert "validate_worker_canary_receipt" in function_source


def test_worker_acceptance_rejects_stale_or_mismatched_startup_receipt(monkeypatch, tmp_path):
    revision = "2" * 40
    worker_pid = 5001
    monkeypatch.setattr(
        acceptance,
        "validate_worker_canary_receipt",
        lambda *args, **kwargs: {
            "ok": False,
            "blockers": ["worker_start_identity_matches", "worker_pid_matches"],
            "receipt": {},
            "worker_start_token": "new-token",
        },
    )

    with pytest.raises(RuntimeError, match="worker_start_identity_matches,worker_pid_matches"):
        acceptance._worker_acceptance(revision, worker_pid, directory=tmp_path)


def test_worker_process_contract_declares_all_required_queues():
    source = (BACKEND_ROOT / "scripts/android_runtime_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert 'REQUIRED_WORKER_QUEUES = "applications,celery,followup,scraping"' in source
    assert "def _worker_identity_tokens" in source
    assert '"-Q",' in source
    assert "REQUIRED_WORKER_QUEUES," in source
    assert "WORKER_CANARY_MAX_WAIT_SECONDS" not in source
    assert "application_queue_canary" not in source
