"""Locked Phase B ingestion merged with the verified Phase A baseline.

The checked-in Phase A CSV is read-only and contains 30 artifact-backed dry-run
records. Runtime ingestion writes only independently confirmed supervised records
to a separate JSONL ledger. Readiness merges both sources under the runtime ledger
lock, so historical evidence is counted without being copied or rewritten.
"""

from __future__ import annotations

import csv
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
    DRY_RUN_MODE,
    SUPERVISED_MODE,
    PilotEvidenceError,
    build_readiness_summary,
    load_ledger,
    merge_records,
    render_readiness_markdown,
    validate_record,
    write_ledger,
)
from app.services.submission_evidence_review import build_supervised_pilot_record


settings = get_settings()
PHASE_A_BASELINE_SHA256 = "14634de4146eb828e394137d351f69270773d957a17899656ccc7577257c3729"
PHASE_A_REQUIRED_RECORDS = 30


class GreenhousePilotIngestionError(ValueError):
    pass


def _path(value: Optional[str], fallback: str) -> Path:
    raw = str(value or fallback).strip()
    if not raw:
        raise GreenhousePilotIngestionError("pilot evidence path cannot be empty")
    return Path(raw)


def configured_paths() -> Dict[str, Path]:
    return {
        "baseline": _path(
            getattr(settings, "greenhouse_pilot_baseline_path", None),
            "evidence/greenhouse-phase-a-baseline.csv",
        ),
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


def _file_digest(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _combined_digest(records: list[Dict[str, Any]]) -> str:
    payload = "".join(
        json.dumps(record, sort_keys=True, separators=(",", ":"), default=str) + "\n"
        for record in records
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _optional_int(value: Any) -> Optional[int]:
    text = str(value or "").strip()
    return int(text) if text else None


def load_phase_a_baseline(
    path: Path,
    *,
    expected_sha256: Optional[str] = PHASE_A_BASELINE_SHA256,
    require_complete: bool = True,
) -> list[Dict[str, Any]]:
    """Load and validate the artifact-backed, read-only Phase A index."""

    if not path.is_file():
        raise GreenhousePilotIngestionError(f"Phase A baseline is missing: {path}")
    actual_digest = _file_digest(path)
    if expected_sha256 and actual_digest != expected_sha256:
        raise GreenhousePilotIngestionError(
            f"Phase A baseline digest mismatch: expected {expected_sha256}, got {actual_digest}"
        )

    records: list[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_number, row in enumerate(reader, start=2):
            try:
                record: Dict[str, Any] = {
                    "schema_version": "1.0",
                    "run_id": str(row.get("run_id") or "").strip(),
                    "mode": DRY_RUN_MODE,
                    "completed_at": str(row.get("completed_at") or "").strip() or None,
                    "employer": str(row.get("employer") or "").strip() or None,
                    "role": str(row.get("role") or "").strip() or None,
                    "board_token": str(row.get("board_token") or "").strip() or None,
                    "job_id": str(row.get("job_id") or "").strip() or None,
                    "application_url": str(row.get("application_url") or "").strip() or None,
                    "adapter": "greenhouse",
                    "adapter_version": "1.1.1",
                    "operator": "github-actions:TheHighBrid",
                    "source_reference": str(row.get("source_reference") or "").strip(),
                    "approval_reference": None,
                    "controls_discovered": _optional_int(row.get("controls_discovered")),
                    "controls_filled": _optional_int(row.get("controls_filled")),
                    "controls_skipped": None,
                    "controls_blocked": _optional_int(row.get("controls_blocked")),
                    "policies_used": _optional_int(row.get("policies_used")),
                    "uploads_verified": _optional_int(row.get("uploads_verified")),
                    "validation_errors": [],
                    "handoff_reason": str(row.get("handoff_reason") or "").strip() or None,
                    "handoff_boundary": str(row.get("handoff_boundary") or "").strip() or None,
                    "pre_submit_state": "manual_challenge_handoff",
                    "final_url": str(row.get("application_url") or "").strip() or None,
                    "final_submit_clicked": False,
                    "confirmation_evidence_type": None,
                    "confirmation_evidence_reference": None,
                    "final_status": "needs_review",
                    "duplicate_guard_verified": None,
                    "duplicate_submission_detected": False,
                    "reviewed_by": None,
                    "review_reference": None,
                    "qualifies_for_dry_run_matrix": True,
                    "synthetic_profile": True,
                    "error": "A CAPTCHA or human-verification challenge requires manual completion.",
                    "notes": None,
                }
                validate_record(record)
            except (TypeError, ValueError, PilotEvidenceError) as exc:
                raise GreenhousePilotIngestionError(
                    f"Invalid Phase A baseline row {line_number}: {exc}"
                ) from exc
            if not record["employer"] or not record["source_reference"]:
                raise GreenhousePilotIngestionError(
                    f"Invalid Phase A baseline row {line_number}: employer and source are required"
                )
            records.append(record)

    try:
        records = merge_records([], records)
    except PilotEvidenceError as exc:
        raise GreenhousePilotIngestionError(str(exc)) from exc

    employers = {
        str(record.get("employer") or "").strip().lower()
        for record in records
        if str(record.get("employer") or "").strip()
    }
    invariant_ok = all(
        record.get("mode") == DRY_RUN_MODE
        and record.get("qualifies_for_dry_run_matrix") is True
        and record.get("final_submit_clicked") is False
        and record.get("approval_reference") in {None, ""}
        and record.get("confirmation_evidence_reference") in {None, ""}
        for record in records
    )
    if not invariant_ok:
        raise GreenhousePilotIngestionError("Phase A baseline violates dry-run safety invariants")
    if require_complete and (
        len(records) != PHASE_A_REQUIRED_RECORDS
        or len(employers) != PHASE_A_REQUIRED_RECORDS
    ):
        raise GreenhousePilotIngestionError(
            "Phase A baseline must contain 30 qualifying records from 30 distinct employers"
        )
    return records


def _write_readiness(paths: Dict[str, Path], summary: Dict[str, Any]) -> None:
    _atomic_replace_text(
        paths["summary_json"],
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
    )
    _atomic_replace_text(
        paths["summary_markdown"],
        render_readiness_markdown(summary),
    )


def _load_combined(paths: Dict[str, Path]) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]]]:
    baseline = load_phase_a_baseline(paths["baseline"])
    runtime = load_ledger(paths["ledger"])
    try:
        combined = merge_records(baseline, runtime)
    except PilotEvidenceError as exc:
        raise GreenhousePilotIngestionError(str(exc)) from exc
    return baseline, runtime, combined


def _readiness_payload(
    paths: Dict[str, Path],
    baseline: list[Dict[str, Any]],
    runtime: list[Dict[str, Any]],
    combined: list[Dict[str, Any]],
) -> Dict[str, Any]:
    summary = build_readiness_summary(combined)
    return {
        "summary": summary,
        "baseline_record_count": len(baseline),
        "runtime_record_count": len(runtime),
        "ledger_record_count": len(combined),
        "baseline_sha256": _file_digest(paths["baseline"]),
        "runtime_ledger_sha256": _file_digest(paths["ledger"]),
        "ledger_sha256": _combined_digest(combined),
    }


def read_greenhouse_pilot_readiness(
    *,
    baseline_path: Optional[str | Path] = None,
    ledger_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    paths = configured_paths()
    if baseline_path is not None:
        paths["baseline"] = Path(baseline_path)
    if ledger_path is not None:
        paths["ledger"] = Path(ledger_path)
    expected_digest = PHASE_A_BASELINE_SHA256 if baseline_path is None else None
    with _ledger_lock(paths["ledger"], exclusive=False):
        baseline = load_phase_a_baseline(
            paths["baseline"], expected_sha256=expected_digest, require_complete=True
        )
        runtime = load_ledger(paths["ledger"])
        try:
            combined = merge_records(baseline, runtime)
        except PilotEvidenceError as exc:
            raise GreenhousePilotIngestionError(str(exc)) from exc
        return _readiness_payload(paths, baseline, runtime, combined)


def ingest_confirmed_supervised_application(
    db: Session,
    application: Application,
    user: User,
    job: Job,
    *,
    baseline_path: Optional[str | Path] = None,
    ledger_path: Optional[str | Path] = None,
    summary_json_path: Optional[str | Path] = None,
    summary_markdown_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Append one confirmed Phase B record while preserving Phase A immutability."""

    try:
        record = build_supervised_pilot_record(db, application, user, job)
    except (ValueError, PilotEvidenceError) as exc:
        raise GreenhousePilotIngestionError(str(exc)) from exc
    if record.get("mode") != SUPERVISED_MODE:
        raise GreenhousePilotIngestionError("Runtime pilot ingestion accepts supervised records only")

    paths = configured_paths()
    if baseline_path is not None:
        paths["baseline"] = Path(baseline_path)
    if ledger_path is not None:
        paths["ledger"] = Path(ledger_path)
    if summary_json_path is not None:
        paths["summary_json"] = Path(summary_json_path)
    if summary_markdown_path is not None:
        paths["summary_markdown"] = Path(summary_markdown_path)
    expected_digest = PHASE_A_BASELINE_SHA256 if baseline_path is None else None

    with _ledger_lock(paths["ledger"], exclusive=True):
        try:
            baseline = load_phase_a_baseline(
                paths["baseline"], expected_sha256=expected_digest, require_complete=True
            )
            runtime = load_ledger(paths["ledger"])
            existing = merge_records(baseline, runtime)
            existing_ids = {str(item.get("run_id")) for item in existing}
            combined = merge_records(existing, [record])
            added = record["run_id"] not in existing_ids
            if added:
                updated_runtime = merge_records(runtime, [record])
                _atomic_write_ledger(paths["ledger"], updated_runtime)
            else:
                updated_runtime = runtime
            summary = build_readiness_summary(combined)
            _write_readiness(paths, summary)
            payload = _readiness_payload(paths, baseline, updated_runtime, combined)
        except PilotEvidenceError as exc:
            raise GreenhousePilotIngestionError(str(exc)) from exc

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
                    "ledger_sha256": payload["ledger_sha256"],
                    "baseline_record_count": payload["baseline_record_count"],
                    "runtime_record_count": payload["runtime_record_count"],
                    "human_reviewed_submit_ready": summary["human_reviewed_submit_ready"],
                },
            )
        )

    return {"added": added, "record": record, **payload}


__all__ = [
    "GreenhousePilotIngestionError",
    "PHASE_A_BASELINE_SHA256",
    "configured_paths",
    "ingest_confirmed_supervised_application",
    "load_phase_a_baseline",
    "read_greenhouse_pilot_readiness",
]
