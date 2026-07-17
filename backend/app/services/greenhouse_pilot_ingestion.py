"""Locked, idempotent ingestion of confirmed runtime pilot records.

This module is evidence-only. It builds the supervised record from trusted
server-side database state, validates it with the canonical pilot ledger rules,
and appends it under an exclusive file lock. It cannot accept an arbitrary
client-supplied record, enable live submission, or provide a release approval.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import Application, ApplicationEvent
from app.models.job import Job
from app.models.user import User
from app.services.greenhouse_pilot import (
    PilotEvidenceError,
    build_readiness_summary,
    load_ledger,
    merge_records,
    render_readiness_markdown,
    write_ledger,
)
from app.services.submission_evidence_review import build_supervised_pilot_record


settings = get_settings()


class GreenhousePilotIngestionError(ValueError):
    pass


def _path(value: Optional[str], fallback: str) -> Path:
    raw = str(value or fallback).strip()
    if not raw:
        raise GreenhousePilotIngestionError("pilot evidence path cannot be empty")
    return Path(raw)


def configured_paths() -> Dict[str, Path]:
    return {
        "ledger": _path(
            getattr(settings, "greenhouse_pilot_ledger_path", None),
            "evidence/greenhouse-pilot-ledger.jsonl",
        ),
        "summary_json": _path(
            getattr(settings, "greenhouse_pilot_readiness_json_path", None),
            "evidence/greenhouse-pilot-readiness.json",
        ),
        "summary_markdown": _path(
            getattr(settings, "greenhouse_pilot_readiness_markdown_path", None),
            "evidence/greenhouse-pilot-readiness.md",
        ),
    }


def _lock_path(ledger_path: Path) -> Path:
    return ledger_path.with_name(ledger_path.name + ".lock")


@contextmanager
def _ledger_lock(ledger_path: Path, *, exclusive: bool) -> Iterator[None]:
    lock_path = _lock_path(ledger_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_replace_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _atomic_write_ledger(path: Path, records: list[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        write_ledger(temporary, records)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _ledger_digest(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_readiness(paths: Dict[str, Path], summary: Dict[str, Any]) -> None:
    _atomic_replace_text(
        paths["summary_json"],
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
    )
    _atomic_replace_text(
        paths["summary_markdown"],
        render_readiness_markdown(summary),
    )


def read_greenhouse_pilot_readiness(
    *,
    ledger_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    paths = configured_paths()
    if ledger_path is not None:
        paths["ledger"] = Path(ledger_path)
    with _ledger_lock(paths["ledger"], exclusive=False):
        records = load_ledger(paths["ledger"])
        summary = build_readiness_summary(records)
        return {
            "summary": summary,
            "ledger_record_count": len(records),
            "ledger_sha256": _ledger_digest(paths["ledger"]),
        }


def ingest_confirmed_supervised_application(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    ledger_path: Optional[str | Path] = None,
    summary_json_path: Optional[str | Path] = None,
    summary_markdown_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Append one server-built confirmed record and refresh readiness reports."""

    try:
        record = build_supervised_pilot_record(db, application, user, job)
    except (ValueError, PilotEvidenceError) as exc:
        raise GreenhousePilotIngestionError(str(exc)) from exc

    paths = configured_paths()
    if ledger_path is not None:
        paths["ledger"] = Path(ledger_path)
    if summary_json_path is not None:
        paths["summary_json"] = Path(summary_json_path)
    if summary_markdown_path is not None:
        paths["summary_markdown"] = Path(summary_markdown_path)

    with _ledger_lock(paths["ledger"], exclusive=True):
        try:
            existing = load_ledger(paths["ledger"])
            existing_ids = {str(item.get("run_id")) for item in existing}
            merged = merge_records(existing, [record])
            added = record["run_id"] not in existing_ids
            _atomic_write_ledger(paths["ledger"], merged)
            summary = build_readiness_summary(merged)
            _write_readiness(paths, summary)
        except PilotEvidenceError as exc:
            raise GreenhousePilotIngestionError(str(exc)) from exc

    digest = _ledger_digest(paths["ledger"])
    if added:
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="supervised_pilot_record_ingested",
                from_state=application.automation_state,
                to_state=application.automation_state,
                payload={
                    "run_id": record["run_id"],
                    "approval_reference": record["approval_reference"],
                    "review_reference": record["review_reference"],
                    "ledger_sha256": digest,
                    "human_reviewed_submit_ready": summary["human_reviewed_submit_ready"],
                },
            )
        )

    return {
        "added": added,
        "record": record,
        "summary": summary,
        "ledger_record_count": len(merged),
        "ledger_sha256": digest,
    }


__all__ = [
    "GreenhousePilotIngestionError",
    "configured_paths",
    "ingest_confirmed_supervised_application",
    "read_greenhouse_pilot_readiness",
]
