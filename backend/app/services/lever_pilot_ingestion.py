"""Locked evidence ingestion and readiness reporting for the Lever pilot.

Lever evidence is isolated from Greenhouse files. Phase A records may be indexed
from an immutable CSV when retained artifacts exist; the runtime JSONL accepts only
Phase B supervised records after independent evidence review and exact-target checks.
"""

from __future__ import annotations

import csv
import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.application import Application, ApplicationEvent
from app.models.job import Job
from app.models.user import User
from app.services.ats_lever import (
    LEVER_ADAPTER_VERSION,
    LEVER_EU_JOBS_HOST,
    LEVER_GLOBAL_JOBS_HOST,
    parse_lever_job_url,
)
from app.services.greenhouse_pilot import (
    DRY_RUN_MODE,
    SUCCESS_STATUSES,
    SUPERVISED_MODE,
    UNCERTAIN_STATUS,
    PilotEvidenceError,
    validate_record,
)
from app.services.platform_submission_evidence import build_platform_supervised_pilot_record


settings = get_settings()
LEVER_PLATFORM = "lever"
PHASE_A_REQUIRED_RECORDS = 30
PHASE_B_REQUIRED_RECORDS = 10
VALID_REGIONS = {"global", "eu"}
PHASE_A_SUCCESS_PAIRS = {
    ("ready_to_submit", "dry_run_passed"),
    ("manual_challenge_handoff", "needs_review"),
}
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class LeverPilotIngestionError(ValueError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _path(value: Optional[str], fallback: str) -> Path:
    raw = str(value or fallback).strip()
    if not raw:
        raise LeverPilotIngestionError("Lever pilot evidence path cannot be empty")
    return Path(raw)


def configured_paths() -> Dict[str, Path]:
    return {
        "baseline": _path(
            getattr(settings, "lever_pilot_baseline_path", None),
            "evidence/lever-phase-a-baseline.csv",
        ),
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
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _combined_digest(records: Iterable[Mapping[str, Any]]) -> str:
    payload = "".join(_canonical_json(record) + "\n" for record in records)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _optional_int(value: Any) -> Optional[int]:
    text = str(value or "").strip()
    return int(text) if text else None


def _phase_a_outcome_qualifies(record: Mapping[str, Any]) -> bool:
    state = str(record.get("pre_submit_state") or "").strip()
    status = str(record.get("final_status") or "").strip()
    return (state, status) in PHASE_A_SUCCESS_PAIRS


def _validate_sha256(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not _SHA256_RE.fullmatch(text):
        raise LeverPilotIngestionError(f"{field} must be a 64-character hexadecimal SHA-256")
    return text.lower()


def _expected_lever_url(site: str, posting_id: str, region: str) -> str:
    host = LEVER_EU_JOBS_HOST if region == "eu" else LEVER_GLOBAL_JOBS_HOST
    return f"https://{host}/{site}/{posting_id}/apply"


def _validate_exact_lever_target(record: Mapping[str, Any]) -> None:
    site = str(record.get("site") or "").strip()
    posting_id = str(record.get("posting_id") or "").strip()
    region = str(record.get("region") or "").strip().lower()
    canonical_url = str(record.get("canonical_application_url") or "").strip()

    if not site or not posting_id or region not in VALID_REGIONS or not canonical_url:
        raise LeverPilotIngestionError(
            "Lever records require site, posting_id, region, and canonical_application_url"
        )

    expected_url = _expected_lever_url(site, posting_id, region)
    parsed = urlparse(canonical_url)
    expected_host = LEVER_EU_JOBS_HOST if region == "eu" else LEVER_GLOBAL_JOBS_HOST
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").lower() != expected_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or canonical_url.rstrip("/") != expected_url
    ):
        raise LeverPilotIngestionError(
            "Lever canonical_application_url must exactly match the claimed site, posting_id, and region"
        )

    observed_site, observed_posting_id, observed_region = parse_lever_job_url(canonical_url)
    if (
        observed_site != site
        or observed_posting_id != posting_id
        or observed_region != region
    ):
        raise LeverPilotIngestionError(
            "Lever canonical_application_url target identity does not match the claimed record identity"
        )

    application_url = str(record.get("application_url") or "").strip()
    if application_url and application_url.rstrip("/") != expected_url:
        raise LeverPilotIngestionError(
            "Lever application_url must match canonical_application_url and the claimed target identity"
        )
    board_token = str(record.get("board_token") or "").strip()
    job_id = str(record.get("job_id") or "").strip()
    if board_token and board_token != site:
        raise LeverPilotIngestionError("Lever board_token must match site")
    if job_id and job_id != posting_id:
        raise LeverPilotIngestionError("Lever job_id must match posting_id")


def validate_phase_a_record(record: Mapping[str, Any]) -> None:
    """Validate integrity and target identity for one immutable Phase A record."""

    if record.get("mode") != DRY_RUN_MODE:
        raise LeverPilotIngestionError("Lever Phase A records must use dry_run mode")
    if record.get("final_submit_clicked") is not False:
        raise LeverPilotIngestionError("Lever Phase A records must record final_submit_clicked=false")
    if str(record.get("adapter_version") or "").strip() != LEVER_ADAPTER_VERSION:
        raise LeverPilotIngestionError(
            "Lever Phase A adapter_version must be explicitly recorded as "
            f"{LEVER_ADAPTER_VERSION}"
        )
    if not str(record.get("operator") or "").strip():
        raise LeverPilotIngestionError("Lever Phase A records require operator")
    if not str(record.get("source_reference") or "").strip():
        raise LeverPilotIngestionError("Lever Phase A records require immutable source_reference")
    _validate_sha256(record.get("artifact_sha256"), field="artifact_sha256")
    _validate_exact_lever_target(record)

    if str(record.get("approval_reference") or "").strip():
        raise LeverPilotIngestionError("Lever Phase A records cannot contain approval_reference")
    if str(record.get("confirmation_evidence_reference") or "").strip():
        raise LeverPilotIngestionError(
            "Lever Phase A records cannot contain confirmation_evidence_reference"
        )

    qualifies = record.get("qualifies_for_dry_run_matrix") is True
    if qualifies and not _phase_a_outcome_qualifies(record):
        raise LeverPilotIngestionError(
            "Lever Phase A record cannot qualify unless its pre-submit state and final status "
            "represent a successful dry-run outcome"
        )


def validate_lever_record(record: Mapping[str, Any]) -> None:
    try:
        validate_record(record)
    except PilotEvidenceError as exc:
        raise LeverPilotIngestionError(str(exc)) from exc

    platform = str(record.get("platform") or record.get("adapter") or "").strip().lower()
    adapter = str(record.get("adapter") or "").strip().lower()
    if platform != LEVER_PLATFORM or adapter != LEVER_PLATFORM:
        raise LeverPilotIngestionError("Lever ledger accepts Lever records only")

    _validate_exact_lever_target(record)

    if record.get("mode") == DRY_RUN_MODE:
        validate_phase_a_record(record)

    if record.get("mode") == SUPERVISED_MODE:
        required = (
            "approval_reference",
            "review_reference",
            "confirmation_evidence_reference",
            "target_identity_hash",
            "posting_metadata_hash",
            "combined_payload_hash",
            "evidence_snapshot_hash",
            "evidence_payload_hash",
        )
        missing = [field for field in required if not str(record.get(field) or "").strip()]
        if missing:
            raise LeverPilotIngestionError(
                "Lever supervised record is missing: " + ", ".join(missing)
            )
        if record.get("evidence_payload_hash") != record.get("combined_payload_hash"):
            raise LeverPilotIngestionError(
                "Lever evidence payload hash must match the consumed approval payload hash"
            )


def validate_phase_b_record(
    record: Mapping[str, Any],
    *,
    line_number: Optional[int] = None,
) -> None:
    """Require one runtime-ledger record to be a Lever supervised Phase B record."""

    location = f" at line {line_number}" if line_number is not None else ""
    if record.get("mode") != SUPERVISED_MODE:
        raise LeverPilotIngestionError(
            "Lever runtime ledger accepts supervised Phase B records only"
            f"{location}; observed mode {record.get('mode')!r}."
        )
    validate_lever_record(record)
    approval_reference = str(record.get("approval_reference") or "").strip()
    if not approval_reference.startswith("lvsup-"):
        raise LeverPilotIngestionError(
            "Lever Phase B records require an lvsup-* approval reference"
            f"{location}; observed {approval_reference or 'missing'}."
        )


def _record_keys(record: Mapping[str, Any]) -> Dict[str, str]:
    values = {
        "run_id": str(record.get("run_id") or "").strip(),
        "approval_reference": str(record.get("approval_reference") or "").strip(),
        "evidence_reference": str(record.get("confirmation_evidence_reference") or "").strip(),
    }
    site = str(record.get("site") or record.get("board_token") or "").strip().lower()
    posting_id = str(record.get("posting_id") or record.get("job_id") or "").strip().lower()
    region = str(record.get("region") or "").strip().lower()
    if site and posting_id and region:
        values["target_identity"] = f"{region}:{site}:{posting_id}"
    return {key: value for key, value in values.items() if value}


def merge_records(
    existing: Iterable[Mapping[str, Any]],
    incoming: Iterable[Mapping[str, Any]],
) -> list[Dict[str, Any]]:
    merged: list[Dict[str, Any]] = []
    seen: Dict[tuple[str, str], Dict[str, Any]] = {}
    for source in (existing, incoming):
        for raw in source:
            record = dict(raw)
            validate_lever_record(record)
            canonical = _canonical_json(record)
            matched_existing = False
            for key_name, key_value in _record_keys(record).items():
                identity = (key_name, key_value)
                prior = seen.get(identity)
                if prior is None:
                    continue
                if _canonical_json(prior) != canonical:
                    raise LeverPilotIngestionError(
                        f"conflicting Lever evidence for {key_name} {key_value}"
                    )
                matched_existing = True
            if matched_existing:
                continue
            merged.append(record)
            for key_name, key_value in _record_keys(record).items():
                seen[(key_name, key_value)] = record
    return merged


def load_ledger(path: Path) -> list[Dict[str, Any]]:
    """Load the runtime JSONL as a strict Phase B-only ledger."""

    if not path.exists():
        return []
    records: list[Dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
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
        records.append(value)
    return merge_records([], records)


def _atomic_write_ledger(path: Path, records: list[Dict[str, Any]]) -> None:
    for record in records:
        validate_phase_b_record(record)
    content = "".join(_canonical_json(record) + "\n" for record in records)
    _atomic_replace_text(path, content)


def load_phase_a_baseline(path: Path) -> list[Dict[str, Any]]:
    """Load an optional immutable Lever Phase A index.

    Missing evidence counts as zero. Integrity or target-identity defects fail closed.
    Failed or incomplete dry runs remain visible but never qualify for readiness gates.
    """

    if not path.is_file():
        return []
    records: list[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_number, row in enumerate(reader, start=2):
            try:
                pre_submit_state = str(row.get("pre_submit_state") or "").strip() or None
                final_status = str(row.get("final_status") or "").strip() or None
                record: Dict[str, Any] = {
                    "schema_version": "1.0",
                    "run_id": str(row.get("run_id") or "").strip(),
                    "mode": DRY_RUN_MODE,
                    "platform": LEVER_PLATFORM,
                    "completed_at": str(row.get("completed_at") or "").strip() or None,
                    "employer": str(row.get("employer") or "").strip() or None,
                    "role": str(row.get("role") or "").strip() or None,
                    "site": str(row.get("site") or "").strip(),
                    "posting_id": str(row.get("posting_id") or "").strip(),
                    "region": str(row.get("region") or "").strip().lower(),
                    "board_token": str(row.get("site") or "").strip(),
                    "job_id": str(row.get("posting_id") or "").strip(),
                    "application_url": str(row.get("application_url") or "").strip(),
                    "canonical_application_url": str(row.get("application_url") or "").strip(),
                    "adapter": LEVER_PLATFORM,
                    "adapter_version": str(row.get("adapter_version") or "").strip(),
                    "operator": str(row.get("operator") or "").strip() or None,
                    "source_reference": str(row.get("source_reference") or "").strip(),
                    "artifact_sha256": str(row.get("artifact_sha256") or "").strip().lower(),
                    "approval_reference": None,
                    "controls_discovered": _optional_int(row.get("controls_discovered")),
                    "controls_filled": _optional_int(row.get("controls_filled")),
                    "controls_skipped": _optional_int(row.get("controls_skipped")),
                    "controls_blocked": _optional_int(row.get("controls_blocked")),
                    "policies_used": _optional_int(row.get("policies_used")),
                    "uploads_verified": _optional_int(row.get("uploads_verified")),
                    "validation_errors": [],
                    "handoff_reason": str(row.get("handoff_reason") or "").strip() or None,
                    "handoff_boundary": str(row.get("handoff_boundary") or "").strip() or None,
                    "pre_submit_state": pre_submit_state,
                    "final_url": str(row.get("application_url") or "").strip(),
                    "final_submit_clicked": False,
                    "confirmation_evidence_type": None,
                    "confirmation_evidence_reference": None,
                    "final_status": final_status,
                    "duplicate_guard_verified": None,
                    "duplicate_submission_detected": False,
                    "reviewed_by": None,
                    "review_reference": None,
                    "qualifies_for_dry_run_matrix": (pre_submit_state, final_status)
                    in PHASE_A_SUCCESS_PAIRS,
                    "synthetic_profile": True,
                    "error": str(row.get("error") or "").strip() or None,
                    "notes": str(row.get("notes") or "").strip() or None,
                }
                validate_lever_record(record)
            except (TypeError, ValueError, LeverPilotIngestionError) as exc:
                raise LeverPilotIngestionError(
                    f"Invalid Lever Phase A baseline row {line_number}: {exc}"
                ) from exc
            records.append(record)
    return merge_records([], records)


def build_readiness_summary(records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    values = [dict(record) for record in records]
    for record in values:
        validate_lever_record(record)

    dry = [
        record
        for record in values
        if record.get("mode") == DRY_RUN_MODE
        and record.get("qualifies_for_dry_run_matrix") is True
        and _phase_a_outcome_qualifies(record)
    ]
    nonqualifying_dry = [
        record for record in values if record.get("mode") == DRY_RUN_MODE and record not in dry
    ]
    sites = {
        str(record.get("site") or "").strip().lower()
        for record in dry
        if str(record.get("site") or "").strip()
    }
    regions = {
        str(record.get("region") or "").strip().lower()
        for record in dry
        if str(record.get("region") or "").strip()
    }
    supervised = [record for record in values if record.get("mode") == SUPERVISED_MODE]
    successes = [record for record in supervised if record.get("final_status") in SUCCESS_STATUSES]
    false_submitted = [
        record
        for record in successes
        if not str(record.get("confirmation_evidence_reference") or "").strip()
    ]
    duplicate_submissions = [
        record for record in supervised if record.get("duplicate_submission_detected") is True
    ]
    uncertain_violations = [
        record
        for record in supervised
        if record.get("pre_submit_state") == UNCERTAIN_STATUS
        and record.get("final_status") != UNCERTAIN_STATUS
    ]
    unreviewed = [
        record
        for record in successes
        if not str(record.get("reviewed_by") or "").strip()
        or not str(record.get("review_reference") or "").strip()
    ]
    hash_mismatches = [
        record
        for record in supervised
        if record.get("evidence_payload_hash") != record.get("combined_payload_hash")
    ]

    gates = {
        "thirty_qualifying_dry_runs": len(dry) >= PHASE_A_REQUIRED_RECORDS,
        "thirty_distinct_lever_sites": len(sites) >= PHASE_A_REQUIRED_RECORDS,
        "global_and_eu_hosts_covered": VALID_REGIONS.issubset(regions),
        "ten_supervised_confirmed_submissions": len(successes) >= PHASE_B_REQUIRED_RECORDS,
        "zero_false_submitted_records": not false_submitted,
        "zero_duplicate_submissions": not duplicate_submissions,
        "all_uncertain_outcomes_remain_uncertain": not uncertain_violations,
        "all_success_evidence_independently_reviewed": bool(successes) and not unreviewed,
        "all_evidence_hashes_match_consumed_approvals": not hash_mismatches,
        "explicit_separate_promotion_approval": False,
    }
    return {
        "schema_version": "1.0",
        "platform": LEVER_PLATFORM,
        "canonical_maturity": "dry_run",
        "record_count": len(values),
        "qualifying_dry_run_count": len(dry),
        "nonqualifying_dry_run_count": len(nonqualifying_dry),
        "distinct_site_count": len(sites),
        "regions_covered": sorted(regions),
        "supervised_record_count": len(supervised),
        "supervised_confirmed_count": len(successes),
        "false_submitted_count": len(false_submitted),
        "duplicate_submission_count": len(duplicate_submissions),
        "uncertain_status_violation_count": len(uncertain_violations),
        "unreviewed_success_count": len(unreviewed),
        "payload_hash_mismatch_count": len(hash_mismatches),
        "gates": gates,
        "supervised_pilot_evidence_complete": all(
            value for key, value in gates.items() if key != "explicit_separate_promotion_approval"
        ),
        "promotion_ready": all(gates.values()),
    }


def render_readiness_markdown(payload: Mapping[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else payload
    gates = summary.get("gates") if isinstance(summary.get("gates"), Mapping) else {}
    lines = [
        "# Lever Supervised Pilot Readiness",
        "",
        "Canonical maturity remains `dry_run`.",
        "",
        "## Progress",
        "",
        f"- Qualifying Phase A dry runs: **{summary.get('qualifying_dry_run_count', 0)}/30**",
        f"- Non-qualifying Phase A rows: **{summary.get('nonqualifying_dry_run_count', 0)}**",
        f"- Distinct Lever sites: **{summary.get('distinct_site_count', 0)}/30**",
        f"- Regions covered: **{', '.join(summary.get('regions_covered') or []) or 'none'}**",
        f"- Confirmed supervised submissions: **{summary.get('supervised_confirmed_count', 0)}/10**",
        "",
        "## Gates",
        "",
    ]
    for name, passed in gates.items():
        lines.append(f"- [{'x' if passed else ' '}] `{name}`")
    lines.extend([
        "",
        f"**Pilot evidence complete:** `{bool(summary.get('supervised_pilot_evidence_complete'))}`",
        f"**Promotion ready:** `{bool(summary.get('promotion_ready'))}`",
        "",
        "Promotion still requires a separate reviewed change with an explicit approval reference.",
        "",
    ])
    return "\n".join(lines)


def _load_combined(
    paths: Dict[str, Path],
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]], list[Dict[str, Any]]]:
    baseline = load_phase_a_baseline(paths["baseline"])
    runtime = load_ledger(paths["ledger"])
    combined = merge_records(baseline, runtime)
    return baseline, runtime, combined


def _readiness_payload(
    paths: Dict[str, Path],
    baseline: list[Dict[str, Any]],
    runtime: list[Dict[str, Any]],
    combined: list[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "summary": build_readiness_summary(combined),
        "baseline_record_count": len(baseline),
        "runtime_record_count": len(runtime),
        "ledger_record_count": len(combined),
        "baseline_sha256": _file_digest(paths["baseline"]),
        "runtime_ledger_sha256": _file_digest(paths["ledger"]),
        "ledger_sha256": _combined_digest(combined),
    }


def _write_readiness(paths: Dict[str, Path], payload: Dict[str, Any]) -> None:
    _atomic_replace_text(
        paths["summary_json"],
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )
    _atomic_replace_text(paths["summary_markdown"], render_readiness_markdown(payload))


def read_lever_pilot_readiness(
    *,
    baseline_path: Optional[str | Path] = None,
    ledger_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    paths = configured_paths()
    if baseline_path is not None:
        paths["baseline"] = Path(baseline_path)
    if ledger_path is not None:
        paths["ledger"] = Path(ledger_path)
    with _ledger_lock(paths["ledger"], exclusive=False):
        baseline, runtime, combined = _load_combined(paths)
        return _readiness_payload(paths, baseline, runtime, combined)


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
    try:
        record = build_platform_supervised_pilot_record(db, application, user, job)
        validate_phase_b_record(record)
    except (ValueError, PilotEvidenceError, LeverPilotIngestionError) as exc:
        raise LeverPilotIngestionError(str(exc)) from exc

    paths = configured_paths()
    overrides = {
        "baseline": baseline_path,
        "ledger": ledger_path,
        "summary_json": summary_json_path,
        "summary_markdown": summary_markdown_path,
    }
    for key, value in overrides.items():
        if value is not None:
            paths[key] = Path(value)

    with _ledger_lock(paths["ledger"], exclusive=True):
        baseline, runtime, existing = _load_combined(paths)
        combined = merge_records(existing, [record])
        added = len(combined) > len(existing)
        updated_runtime = merge_records(runtime, [record]) if added else runtime
        for runtime_record in updated_runtime:
            validate_phase_b_record(runtime_record)
        if added:
            _atomic_write_ledger(paths["ledger"], updated_runtime)
        payload = _readiness_payload(paths, baseline, updated_runtime, combined)
        _write_readiness(paths, payload)

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
                    "site": record["site"],
                    "posting_id": record["posting_id"],
                    "region": record["region"],
                    "ledger_sha256": payload["ledger_sha256"],
                    "runtime_record_count": payload["runtime_record_count"],
                    "promotion_ready": payload["summary"]["promotion_ready"],
                },
            )
        )

    return {"added": added, "record": record, **payload}


__all__ = [
    "LeverPilotIngestionError",
    "build_readiness_summary",
    "configured_paths",
    "ingest_confirmed_lever_application",
    "load_phase_a_baseline",
    "read_lever_pilot_readiness",
    "validate_lever_record",
    "validate_phase_a_record",
    "validate_phase_b_record",
]
