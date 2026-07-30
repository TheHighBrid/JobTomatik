"""Retained-artifact verification for Lever Phase A qualification.

CSV rows are an index only. Recognized Phase A rows must be backed by a retained
JSON artifact whose bytes match the recorded SHA-256 and whose exercise and
official posting inspection independently certify the exact Lever target.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.services.ats_lever import LEVER_ADAPTER_VERSION, parse_lever_job_url

PHASE_A_READY_PAIR = ("ready_to_submit", "dry_run_passed")
PHASE_A_BOUNDARY_PAIR = ("manual_challenge_handoff", "needs_review")
MANUAL_CHALLENGE_REASON_CODES = frozenset(
    {
        "captcha_detected",
        "mfa_required",
        "login_required",
        "anti_bot_challenge",
    }
)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _same_url(left: Any, right: Any) -> bool:
    return str(left or "").strip().rstrip("/") == str(right or "").strip().rstrip("/")


def _artifact_path(
    baseline_path: Optional[str | Path], row: Mapping[str, Any]
) -> Optional[Path]:
    raw = str(row.get("artifact_path") or "").strip()
    if not raw or baseline_path is None:
        return None
    relative = Path(raw)
    if relative.is_absolute():
        return None
    root = Path(baseline_path).resolve().parent
    resolved = (root / relative).resolve()
    if resolved != root and root not in resolved.parents:
        return None
    return resolved


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manual_challenge_exercise_verified(exercise: Mapping[str, Any]) -> bool:
    raw_review_items = exercise.get("review_items") or []
    validation_errors = exercise.get("validation_errors") or []
    if not isinstance(raw_review_items, list) or not isinstance(validation_errors, list):
        return False
    if any(not isinstance(item, dict) for item in raw_review_items):
        return False

    reason_codes = [str(item.get("reason_code") or "").strip() for item in raw_review_items]
    challenge_items = [
        code for code in reason_codes if code in MANUAL_CHALLENGE_REASON_CODES
    ]
    blocking_items = [
        code for code in reason_codes if code not in MANUAL_CHALLENGE_REASON_CODES
    ]
    return bool(
        exercise.get("manual_challenge_ready") is True
        and exercise.get("ready_to_submit") is False
        and exercise.get("requires_manual_review") is True
        and challenge_items
        and not blocking_items
        and not validation_errors
    )


def verify_phase_a_row_evidence(
    row: Mapping[str, Any], *, baseline_path: Optional[str | Path]
) -> Dict[str, Any]:
    """Verify one CSV index row against its retained artifact.

    Ready-to-submit rows qualify only when every artifact, target, adapter,
    exercise, and inspection invariant matches. Manual-challenge rows are also
    independently verified so their evidence flags are truthful, but they remain
    boundary-only and never advance the Phase A qualifying count.
    """

    pair = (
        str(row.get("pre_submit_state") or "").strip(),
        str(row.get("final_status") or "").strip(),
    )
    candidate = pair == PHASE_A_READY_PAIR
    boundary = pair == PHASE_A_BOUNDARY_PAIR
    recognized = candidate or boundary
    claimed_inspection = _truthy(row.get("official_posting_inspection_passed"))
    result: Dict[str, Any] = {
        "candidate": candidate,
        "boundary": boundary,
        "recognized": recognized,
        "claimed_inspection_passed": claimed_inspection,
        "artifact_verified": False,
        "exercise_verified": False,
        "inspection_verified": False,
        "evidence_verified": False,
        "boundary_verified": False,
        "qualifies": False,
        "error": None,
    }
    if not recognized:
        return result

    artifact = _artifact_path(baseline_path, row)
    if artifact is None:
        result["error"] = "recognized Phase A rows require a safe relative artifact_path"
        return result
    if not artifact.is_file():
        result["error"] = f"retained Phase A artifact is missing: {artifact.name}"
        return result

    expected_digest = str(row.get("artifact_sha256") or "").strip().lower()
    actual_digest = _sha256(artifact)
    if not expected_digest or actual_digest != expected_digest:
        result["error"] = "retained Phase A artifact SHA-256 does not match the CSV index"
        return result

    try:
        report = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        result["error"] = f"retained Phase A artifact is not valid JSON: {exc}"
        return result
    if not isinstance(report, dict):
        result["error"] = "retained Phase A artifact must be a JSON object"
        return result
    if report.get("final_submit_clicked") is not False:
        result["error"] = "retained Phase A artifact must record final_submit_clicked=false"
        return result

    url = str(row.get("application_url") or "").strip()
    site = str(row.get("site") or "").strip()
    posting_id = str(row.get("posting_id") or "").strip()
    region = str(row.get("region") or "").strip().lower()
    observed_site, observed_posting_id, observed_region = parse_lever_job_url(url)
    if (observed_site, observed_posting_id, observed_region) != (site, posting_id, region):
        result["error"] = "CSV target identity does not match the exact Lever application URL"
        return result

    # Artifact verification is independent from whether the retained report
    # ultimately proves a qualifying exercise or a valid manual boundary.
    result["artifact_verified"] = True

    reports = report.get("reports") or []
    if not isinstance(reports, list):
        result["error"] = "retained Phase A artifact reports must be a list"
        return result
    inspections = [
        item
        for item in reports
        if isinstance(item, dict)
        and item.get("mode") == "inspect"
        and _same_url(item.get("url"), url)
    ]
    exercises = [
        item
        for item in reports
        if isinstance(item, dict)
        and item.get("mode") == "exercise"
        and _same_url(item.get("url"), url)
    ]
    if len(inspections) != 1:
        result["error"] = "exactly one retained matching official-posting inspection is required"
        return result
    if len(exercises) != 1:
        result["error"] = "exactly one retained matching Lever dry-run exercise is required"
        return result

    inspection = inspections[0]
    inspection_verified = (
        inspection.get("passed") is True
        and inspection.get("adapter") == "lever"
        and str(inspection.get("adapter_version") or "") == LEVER_ADAPTER_VERSION
        and inspection.get("final_submit_clicked") is False
    )
    exercise = exercises[0]
    exercise_base_verified = (
        exercise.get("passed") is True
        and exercise.get("adapter") == "lever"
        and str(exercise.get("adapter_version") or "") == LEVER_ADAPTER_VERSION
        and exercise.get("final_submit_clicked") is False
    )
    if candidate:
        exercise_verified = bool(
            exercise_base_verified
            and exercise.get("certification_outcome") == "ready_to_submit"
        )
    else:
        exercise_verified = bool(
            exercise_base_verified
            and exercise.get("certification_outcome") == "manual_challenge_handoff"
            and _manual_challenge_exercise_verified(exercise)
        )

    evidence_verified = bool(
        result["artifact_verified"]
        and claimed_inspection
        and exercise_verified
        and inspection_verified
    )
    result.update(
        {
            "exercise_verified": exercise_verified,
            "inspection_verified": inspection_verified,
            "evidence_verified": evidence_verified,
            "boundary_verified": bool(boundary and evidence_verified),
            "qualifies": bool(candidate and evidence_verified),
        }
    )
    if candidate and not result["qualifies"]:
        result["error"] = (
            "retained artifact does not independently verify the claimed successful "
            "exercise and official-posting inspection"
        )
    elif boundary and not result["boundary_verified"]:
        result["error"] = (
            "retained artifact does not independently verify the manual-challenge "
            "handoff and official-posting inspection"
        )
    return result


__all__ = [
    "MANUAL_CHALLENGE_REASON_CODES",
    "PHASE_A_BOUNDARY_PAIR",
    "PHASE_A_READY_PAIR",
    "verify_phase_a_row_evidence",
]
