from __future__ import annotations

import json
from pathlib import Path

from app.services.android_worker_canary import (
    validate_worker_canary_receipt,
    write_worker_canary_receipt,
)


def _write_proc_stat(proc_root: Path, pid: int, start_token: str) -> None:
    proc_dir = proc_root / str(pid)
    proc_dir.mkdir(parents=True, exist_ok=True)
    fields = ["S"] + ["0"] * 18 + [str(start_token)] + ["0"] * 8
    (proc_dir / "stat").write_text(
        f"{pid} (celery worker) " + " ".join(fields) + "\n",
        encoding="utf-8",
    )


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
        "runtime_identity_sha256": "b" * 64,
    }


def test_startup_canary_receipt_binds_exact_pid_start_token_revision_and_db1(tmp_path):
    revision = "a" * 40
    worker_pid = 4242
    proc_root = tmp_path / "proc"
    receipt_path = tmp_path / "runtime" / "celery-application-canary.json"
    _write_proc_stat(proc_root, worker_pid, "987654")

    written = write_worker_canary_receipt(
        receipt_path,
        payload=_payload(revision, worker_pid),
        expected_revision=revision,
        expected_worker_pid=worker_pid,
        declared_queues=["applications", "celery", "followup", "scraping"],
        proc_root=proc_root,
    )

    assert written["worker_start_token"] == "987654"
    assert written["redis_db"] == 1
    assert written["worker_pid"] == worker_pid
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["proof"] == (
        "startup_exact_worker_db1_round_trip"
    )

    status = validate_worker_canary_receipt(
        receipt_path,
        expected_revision=revision,
        expected_worker_pid=worker_pid,
        required_queues=["applications", "celery", "followup", "scraping"],
        proc_root=proc_root,
    )
    assert status["ok"] is True
    assert status["blockers"] == []


def test_startup_canary_receipt_rejects_pid_reuse_even_when_numeric_pid_matches(tmp_path):
    revision = "c" * 40
    worker_pid = 5252
    proc_root = tmp_path / "proc"
    receipt_path = tmp_path / "runtime" / "celery-application-canary.json"
    _write_proc_stat(proc_root, worker_pid, "111")
    write_worker_canary_receipt(
        receipt_path,
        payload=_payload(revision, worker_pid),
        expected_revision=revision,
        expected_worker_pid=worker_pid,
        declared_queues=["applications", "celery", "followup", "scraping"],
        proc_root=proc_root,
    )

    _write_proc_stat(proc_root, worker_pid, "222")
    status = validate_worker_canary_receipt(
        receipt_path,
        expected_revision=revision,
        expected_worker_pid=worker_pid,
        required_queues=["applications", "celery", "followup", "scraping"],
        proc_root=proc_root,
    )

    assert status["ok"] is False
    assert "worker_start_identity_matches" in status["blockers"]


def test_startup_canary_receipt_rejects_wrong_revision_queue_or_worker(tmp_path):
    revision = "d" * 40
    worker_pid = 6262
    proc_root = tmp_path / "proc"
    receipt_path = tmp_path / "runtime" / "celery-application-canary.json"
    _write_proc_stat(proc_root, worker_pid, "333")
    write_worker_canary_receipt(
        receipt_path,
        payload=_payload(revision, worker_pid),
        expected_revision=revision,
        expected_worker_pid=worker_pid,
        declared_queues=["applications", "celery", "followup", "scraping"],
        proc_root=proc_root,
    )

    _write_proc_stat(proc_root, worker_pid + 1, "444")
    status = validate_worker_canary_receipt(
        receipt_path,
        expected_revision="e" * 40,
        expected_worker_pid=worker_pid + 1,
        required_queues=["applications"],
        proc_root=proc_root,
    )

    assert status["ok"] is False
    assert "revision_matches" in status["blockers"]
    assert "worker_pid_matches" in status["blockers"]
    assert "declared_queues_match" in status["blockers"]
