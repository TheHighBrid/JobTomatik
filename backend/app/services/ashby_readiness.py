"""Build retained, fail-closed Ashby dry-run certification evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


DOSSIER_SCHEMA_VERSION = "1.0"
ASHBY_MATURITY = "dry_run"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _junit_summary(path: Path) -> Dict[str, Any]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    failures = sum(int(suite.attrib.get("failures", 0)) for suite in suites)
    errors = sum(int(suite.attrib.get("errors", 0)) for suite in suites)
    skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
    return {
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "passed": tests > 0 and failures == 0 and errors == 0,
    }


def _target_identity(url: str) -> Optional[str]:
    parsed = urlparse(url or "")
    parts = [part for part in parsed.path.split("/") if part]
    if (parsed.hostname or "").lower() != "jobs.ashbyhq.com" or len(parts) < 2:
        return None
    return f"{parts[0]}:{parts[1]}"


def _lane_targets(report: Dict[str, Any]) -> List[str]:
    identities: List[str] = []
    for item in report.get("reports") or []:
        if not isinstance(item, dict):
            continue
        identity = _target_identity(str(item.get("surface_url") or item.get("url") or ""))
        if identity and identity not in identities:
            identities.append(identity)
    return identities


def _raw_lane_target_count(report: Dict[str, Any]) -> int:
    values = []
    for item in report.get("reports") or []:
        if not isinstance(item, dict):
            continue
        identity = _target_identity(str(item.get("surface_url") or item.get("url") or ""))
        if identity:
            values.append(identity)
    return len(values)


def _verified_uploads(report: Dict[str, Any]) -> int:
    return sum(
        1
        for item in report.get("reports") or []
        if isinstance(item, dict) and item.get("mode") == "exercise"
        for upload in item.get("upload_evidence") or []
        if isinstance(upload, dict) and upload.get("verification") == "passed"
    )


def _manual_challenge_outcomes(report: Dict[str, Any]) -> int:
    return sum(
        1
        for item in report.get("reports") or []
        if isinstance(item, dict)
        and item.get("mode") == "exercise"
        and item.get("certification_outcome") == "manual_challenge_handoff"
    )


def _all_final_submit_false(report: Dict[str, Any]) -> bool:
    if report.get("final_submit_clicked") is not False:
        return False
    return all(
        item.get("final_submit_clicked") is False
        for item in report.get("reports") or []
        if isinstance(item, dict)
    )


def _official_schema_statuses(report: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for item in report.get("reports") or []:
        if not isinstance(item, dict) or item.get("mode") != "inspect":
            continue
        status = str(item.get("official_form_definition_status") or "unknown")
        if status not in values:
            values.append(status)
    return values


def _input_record(path: Path, *, kind: str) -> Dict[str, Any]:
    return {
        "kind": kind,
        "path": path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def build_ashby_certification_dossier(
    *,
    fixture_junit: Path,
    handoff_junit: Path,
    live_smoke_json: Path,
    synthetic_live_json: Path,
    source_commit: str,
    generated_at: str,
    adapter_version: str,
    repository: str = "TheHighBrid/JobTomatik",
) -> Dict[str, Any]:
    """Combine locked Ashby CI inputs into a truthful retained dossier.

    This dossier proves only a dry-run boundary. It cannot credit real submissions,
    confirmation evidence from a real submit, supervised promotion, or autonomous
    readiness.
    """
    fixture = _junit_summary(fixture_junit)
    handoff = _junit_summary(handoff_junit)
    live = _load_json(live_smoke_json)
    synthetic = _load_json(synthetic_live_json)

    live_targets = _lane_targets(live)
    synthetic_targets = _lane_targets(synthetic)
    distinct_targets = list(dict.fromkeys([*live_targets, *synthetic_targets]))

    live_raw_count = _raw_lane_target_count(live)
    synthetic_raw_count = _raw_lane_target_count(synthetic)
    live_duplicate_targets = max(live_raw_count - len(live_targets), 0)
    synthetic_duplicate_targets = max(
        synthetic_raw_count - len(synthetic_targets), 0
    )

    uploads_verified = _verified_uploads(synthetic)
    manual_challenge_outcomes = _manual_challenge_outcomes(synthetic)
    official_schema_statuses = _official_schema_statuses(live)

    live_passed = bool(live.get("passed")) and _all_final_submit_false(live)
    synthetic_passed = bool(synthetic.get("passed")) and _all_final_submit_false(
        synthetic
    )
    fixture_passed = fixture["passed"]
    handoff_passed = handoff["passed"]

    blockers: List[str] = []
    if not fixture_passed:
        blockers.append("fixture_matrix_failed")
    if not live_passed:
        blockers.append("live_public_form_inspection_failed")
    if not synthetic_passed:
        blockers.append("synthetic_live_exercise_failed")
    if not handoff_passed:
        blockers.append("resumable_handoff_matrix_failed")
    if uploads_verified < 1:
        blockers.append("no_verified_live_form_upload")
    if live_duplicate_targets or synthetic_duplicate_targets:
        blockers.append("duplicate_target_within_certification_lane")
    if not distinct_targets:
        blockers.append("no_current_public_targets")
    if any(value == "error" for value in official_schema_statuses):
        blockers.append("credentialed_form_definition_validation_error")

    dry_run_ready = not blockers

    promotion_blockers = [
        "no_real_supervised_submission_evidence",
        "no_live_post_submit_confirmation_evidence",
        "independent_success_evidence_review_not_present",
        "explicit_adapter_promotion_authorization_required",
    ]
    if "validated" not in official_schema_statuses:
        promotion_blockers.append(
            "credentialed_live_form_definition_validation_not_retained"
        )

    return {
        "schema_version": DOSSIER_SCHEMA_VERSION,
        "platform": "ashby",
        "repository": repository,
        "source_commit": source_commit,
        "generated_at": generated_at,
        "adapter_version": adapter_version,
        "maturity": ASHBY_MATURITY,
        "certification_scope": "dry_run_pre_submit_only",
        "inputs": [
            _input_record(fixture_junit, kind="fixture_matrix_junit"),
            _input_record(handoff_junit, kind="resumable_handoff_junit"),
            _input_record(live_smoke_json, kind="live_public_form_inspection"),
            _input_record(synthetic_live_json, kind="synthetic_live_dry_run"),
        ],
        "fixture_matrix": fixture,
        "resumable_handoff_matrix": handoff,
        "live_public_form_inspection": {
            "passed": live_passed,
            "url_count": int(live.get("url_count") or 0),
            "target_count": len(live_targets),
            "targets": live_targets,
            "duplicate_targets_within_lane": live_duplicate_targets,
            "official_form_definition_statuses": official_schema_statuses,
            "final_submit_clicked": not _all_final_submit_false(live),
        },
        "synthetic_live_dry_run": {
            "passed": synthetic_passed,
            "url_count": int(synthetic.get("url_count") or 0),
            "target_count": len(synthetic_targets),
            "targets": synthetic_targets,
            "duplicate_targets_within_lane": synthetic_duplicate_targets,
            "verified_upload_count": uploads_verified,
            "manual_challenge_handoff_count": manual_challenge_outcomes,
            "accepted_outcomes": [
                item.get("certification_outcome")
                for item in synthetic.get("reports") or []
                if isinstance(item, dict) and item.get("mode") == "exercise"
            ],
            "final_submit_clicked": not _all_final_submit_false(synthetic),
        },
        "coverage": {
            "distinct_current_public_targets": len(distinct_targets),
            "hosted_form_live_inspection": live_passed,
            "embedded_iframe_regression": fixture_passed,
            "query_suffixed_application_regression": fixture_passed,
            "official_form_definition_fixture_validation": fixture_passed,
            "live_official_form_definition_validation_retained": (
                "validated" in official_schema_statuses
            ),
            "verified_upload": uploads_verified > 0,
            "manual_challenge_handoff": (
                manual_challenge_outcomes > 0 or handoff_passed
            ),
            "resumable_handoff": handoff_passed,
            "confirmation_detection_fixture_only": fixture_passed,
            "live_post_submit_confirmation": False,
        },
        "safety": {
            "allow_real_application_submit": False,
            "credited_real_submissions": 0,
            "final_submit_clicked": False,
            "false_submitted_records": 0,
            "uncertain_outcomes_credited_as_submitted": 0,
            "captcha_or_mfa_bypass_attempted": False,
            "maturity_changed": False,
        },
        "readiness": {
            "dry_run_certification_ready": dry_run_ready,
            "human_reviewed_submit_ready": False,
            "autonomous_ready": False,
            "promotion_ready": False,
            "dry_run_blockers": blockers,
            "promotion_blockers": promotion_blockers,
        },
    }
