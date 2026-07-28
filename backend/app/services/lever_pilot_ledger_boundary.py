"""Fail-closed platform and phase boundary for the Lever pilot runtime ledger.

The underlying ingestion module owns normalization, locking, atomic writes, and
readiness calculations. This boundary owns the source contract: the optional CSV is
Phase A dry-run evidence, while the runtime JSONL is Phase B supervised evidence only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.job import Job
from app.models.user import User
from app.services.greenhouse_pilot import SUPERVISED_MODE
from app.services.lever_pilot_ingestion import (
    LeverPilotIngestionError,
    configured_paths,
    ingest_confirmed_lever_application as _ingest_confirmed_lever_application,
    read_lever_pilot_readiness as _read_lever_pilot_readiness,
    render_readiness_markdown,
    validate_phase_b_record,
)
from app.services.lever_readiness_hardening import harden_lever_readiness


def _runtime_ledger_path(value: Optional[str | Path]) -> Path:
    if value is not None:
        return Path(value)
    return configured_paths()["ledger"]


def _baseline_path(value: Optional[str | Path]) -> Path:
    if value is not None:
        return Path(value)
    return configured_paths()["baseline"]


def _summary_path(
    value: Optional[str | Path],
    key: str,
) -> Path:
    if value is not None:
        return Path(value)
    return configured_paths()[key]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def validate_phase_b_runtime_ledger(path: Path) -> list[Dict[str, Any]]:
    """Load a Lever runtime ledger and reject every non-Phase-B record."""

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
                f"invalid Lever Phase B JSONL at line {line_number}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise LeverPilotIngestionError(
                f"Lever Phase B ledger line {line_number} must be a JSON object"
            )

        validate_phase_b_record(value, line_number=line_number)
        records.append(dict(value))
    return records


def read_lever_pilot_readiness(
    *,
    baseline_path: Optional[str | Path] = None,
    ledger_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    runtime_path = _runtime_ledger_path(ledger_path)
    baseline = _baseline_path(baseline_path)
    validate_phase_b_runtime_ledger(runtime_path)
    readiness = _read_lever_pilot_readiness(
        baseline_path=baseline,
        ledger_path=runtime_path,
    )
    return harden_lever_readiness(
        readiness,
        baseline_path=baseline,
        ledger_path=runtime_path,
    )


def ingest_confirmed_lever_application(
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
    runtime_path = _runtime_ledger_path(ledger_path)
    baseline = _baseline_path(baseline_path)
    json_path = _summary_path(summary_json_path, "summary_json")
    markdown_path = _summary_path(summary_markdown_path, "summary_markdown")
    validate_phase_b_runtime_ledger(runtime_path)
    result = _ingest_confirmed_lever_application(
        db,
        application,
        user,
        job,
        baseline_path=baseline,
        ledger_path=runtime_path,
        summary_json_path=json_path,
        summary_markdown_path=markdown_path,
    )
    record = result.get("record") if isinstance(result, dict) else None
    if not isinstance(record, dict) or record.get("mode") != SUPERVISED_MODE:
        raise LeverPilotIngestionError(
            "Lever Phase B ingestion produced a non-supervised record"
        )
    validate_phase_b_runtime_ledger(runtime_path)
    hardened_result = harden_lever_readiness(
        result,
        baseline_path=baseline,
        ledger_path=runtime_path,
    )
    readiness_payload = {
        key: value
        for key, value in hardened_result.items()
        if key not in {"added", "record"}
    }
    _atomic_write(
        json_path,
        json.dumps(readiness_payload, indent=2, sort_keys=True, default=str) + "\n",
    )
    _atomic_write(markdown_path, render_readiness_markdown(readiness_payload))
    return hardened_result


__all__ = [
    "LeverPilotIngestionError",
    "ingest_confirmed_lever_application",
    "read_lever_pilot_readiness",
    "validate_phase_b_runtime_ledger",
]
