"""Locked runtime ledger for independently confirmed Lever submissions.

This service does not create approvals, open browsers, or submit applications. It
accepts only already-confirmed, independently reviewed Lever records and writes
JSONL plus readiness summaries using a process-safe lock and atomic replacement.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import Application, ApplicationEvent
from app.models.job import Job
from app.models.user import User
from app.services.greenhouse_pilot import (
    PilotEvidenceError,
    build_readiness_summary,
    validate_record,
)
from app.services.platform_submission_evidence import (
    build_platform_supervised_pilot_record,
)


settings = get_settings()
LEVER_PLATFORM = "lever"


class LeverPilotIngestionError(ValueError):
    pass


def _path(value: Optional[str], fallback: str) -> Path:
    raw = str(value or fallback).strip()
    if not raw:
        raise LeverPilotIngestionError("Lever pilot evidence path cannot be empty")
    return Path(raw)


def configured_paths() -> Dict[str, Path]:
    return {
        "ledger": _path(
            getattr(settings, "lever_pilot_ledger_path", None),
            "evidence/lever-pilot-ledger.jsonl",
        ),
        "summary_json": _path(
            getattr(settings, "lever_pilot_readiness_json_path", None),
            "evidence/lever-pilot-readiness.json",
        ),
        "summary_markdown": _path(
            getattr(settings, "lever_pilot_readiness_markdown_path", None),
            "evidence/lever-pilot-readiness.md",
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


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), default=str)


def _atomic_replace_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _file_digest(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _combined_digest(records: list[Dict[str, Any]]) -> str:
    payload = "".join(_canonical_json(item) + "\n" for item in records)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_lever_record(record: Mapping[str, Any]) -> None:
    try:
        validate_record(record)
    except PilotEvidenceError as exc:
        raise LeverPilotIngestionError(str(exc)) from exc

    required = {
        "adapter": LEVER_PLATFORM,
        "platform": LEVER_PLATFORM,
        "mode": "supervised_real_submission",
        "final_status": "confirmed",
        "duplicate_submission_detected": False,
    }
    for field, expected in required.items():
        if record.get(field) != expected:
            raise LeverPilotIngestionError(
                f"Lever pilot record requires {field}={expected!r}"
            )
    if record.get("final_submit_clicked") is not True:
        raise LeverPilotIngestionError(
            "Lever supervised records must explicitly record final_submit_clicked=true"
        )
    if not str(record.get("approval_reference") or "").startswith("lvsup-"):
        raise LeverPilotIngestionError("Lever pilot record requires an lvsup approval")

    for field in (
        "review_reference",
        "confirmation_evidence_reference",
        "target_identity_hash",
        "posting_metadata_hash",
        "lever_site",
        "lever_posting_id",
        "lever_region",
        "canonical_application_url",
    ):
        if not str(record.get(field) or "").strip():
            raise LeverPilotIngestionError(
                f"Lever pilot record is missing {field}"
            )


def load_lever_ledger(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    records: list[Dict[str, Any]] = []
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LeverPilotIngestionError(
                f"Invalid Lever pilot JSONL at line {line_number}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise LeverPilotIngestionError(
                f"Lever pilot ledger line {line_number} must be an object"
            )
        _validate_lever_record(value)
        records.append(value)
    return records


def _write_ledger(path: Path, records: list[Dict[str, Any]]) -> None:
    for record in records:
        _validate_lever_record(record)
    payload = "".join(_canonical_json(record) + "\n" for record in records)
    _atomic_replace_text(path, payload)


def _find_conflict(
    existing: list[Dict[str, Any]],
    incoming: Mapping[str, Any],
) -> Optional[str]:
    unique_fields = (
        "approval_reference",
        "review_reference",
        "confirmation_evidence_reference",
        "target_identity_hash",
    )
    for record in existing:
        if record.get("run_id") == incoming.get("run_id"):
            if _canonical_json(record) != _canonical_json(incoming):
                return "run_id"
            continue
        for field in unique_fields:
            value = str(incoming.get(field) or "").strip()
            if value and str(record.get(field) or "").strip() == value:
                return field
    return None


def _readiness(records: list[Dict[str, Any]]) -> Dict[str, Any]:
    summary = build_readiness_summary(records)
    return {
        **summary,
        "platform": LEVER_PLATFORM,
        "runtime_record_count": len(records),
        "phase_a_baseline_present": False,
        "phase_a_baseline_record_count": 0,
    }


def _render_markdown(summary: Mapping[str, Any]) -> str:
    gates = summary.get("gates") if isinstance(summary.get("gates"), Mapping) else {}
    lines = [
        "# Lever Supervised Pilot Readiness",
        "",
        f"Generated: `{summary.get('generated_at')}`",
        "",
        "## Runtime Phase B progress",
        "",
        f"- Confirmed supervised submissions: **{summary.get('supervised_confirmed_count', 0)} / 10**",
        f"- Runtime ledger records: **{summary.get('runtime_record_count', 0)}**",
        "- Phase A baseline: **not attached yet**",
        "",
        "## Release gates",
        "",
        "| Gate | Status |",
        "|---|---|",
    ]
    for name, passed in gates.items():
        lines.append(
            f"| {name.replace('_', ' ').capitalize()} | {'PASS' if passed else 'BLOCKED'} |"
        )
    lines.extend([
        "",
        "Lever remains `dry_run`. This runtime ledger does not promote maturity.",
        "",
    ])
    return "\n".join(lines)


def _write_readiness(paths: Dict[str, Path], summary: Mapping[str, Any]) -> None:
    _atomic_replace_text(
        paths["summary_json"],
        json.dumps(dict(summary), indent=2, sort_keys=True) + "\n",
    )
    _atomic_replace_text(paths["summary_markdown"], _render_markdown(summary))


def read_lever_pilot_readiness(
    *,
    ledger_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    paths = configured_paths()
    if ledger_path is not None:
        paths["ledger"] = Path(ledger_path)
    with _ledger_lock(paths["ledger"], exclusive=False):
        records = load_lever_ledger(paths["ledger"])
        summary = _readiness(records)
        return {
            "summary": summary,
            "ledger_record_count": len(records),
            "ledger_sha256": _combined_digest(records),
            "ledger_file_sha256": _file_digest(paths["ledger"]),
        }


def ingest_confirmed_lever_application(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    ledger_path: Optional[str | Path] = None,
    summary_json_path: Optional[str | Path] = None,
    summary_markdown_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    try:
        record = build_platform_supervised_pilot_record(
            db,
            application,
            user,
            job,
        )
    except ValueError as exc:
        raise LeverPilotIngestionError(str(exc)) from exc
    _validate_lever_record(record)

    paths = configured_paths()
    if ledger_path is not None:
        paths["ledger"] = Path(ledger_path)
    if summary_json_path is not None:
        paths["summary_json"] = Path(summary_json_path)
    if summary_markdown_path is not None:
        paths["summary_markdown"] = Path(summary_markdown_path)

    with _ledger_lock(paths["ledger"], exclusive=True):
        existing = load_lever_ledger(paths["ledger"])
        conflict = _find_conflict(existing, record)
        if conflict:
            same_run = next(
                (
                    item
                    for item in existing
                    if item.get("run_id") == record.get("run_id")
                ),
                None,
            )
            if same_run and _canonical_json(same_run) == _canonical_json(record):
                added = False
                updated = existing
            else:
                raise LeverPilotIngestionError(
                    f"Conflicting Lever pilot evidence for {conflict}"
                )
        else:
            added = True
            updated = [*existing, record]
            _write_ledger(paths["ledger"], updated)

        summary = _readiness(updated)
        _write_readiness(paths, summary)
        payload = {
            "summary": summary,
            "ledger_record_count": len(updated),
            "ledger_sha256": _combined_digest(updated),
            "ledger_file_sha256": _file_digest(paths["ledger"]),
        }

    if added:
        db.add(
            ApplicationEvent(
                application_id=application.id,
                event_type="lever_supervised_pilot_record_ingested",
                from_state=application.automation_state,
                to_state=application.automation_state,
                payload={
                    "run_id": record["run_id"],
                    "approval_reference": record["approval_reference"],
                    "review_reference": record["review_reference"],
                    "target_identity_hash": record["target_identity_hash"],
                    "ledger_sha256": payload["ledger_sha256"],
                    "runtime_record_count": payload["ledger_record_count"],
                },
            )
        )

    return {"added": added, "record": record, **payload}


__all__ = [
    "LeverPilotIngestionError",
    "configured_paths",
    "ingest_confirmed_lever_application",
    "load_lever_ledger",
    "read_lever_pilot_readiness",
]
