"""Day 28 Phase 4 adapter ranking, digest binding, and version-freeze gate.

This module selects a pilot-preparation candidate from retained evidence without
promoting maturity or enabling submission. The output is intentionally
machine-readable so later unattended-pilot work can fail closed on adapter,
fixture, or evidence drift.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.services.ats_manifest import ats_certification_manifest
from app.services.autonomy_release_contract import (
    MIN_RELIABILITY_ATTEMPTS,
    MIN_SUCCESS_RATE,
    REQUIRED_SHADOW_CHECKS,
)
from app.services.operations_policy import operations_readiness_manifest


PHASE4_GATE_VERSION = "day28_v1"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ADAPTERS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workday")
FREEZE_PATH = "backend/evidence/day28-phase4-version-freeze.json"
EVIDENCE_PATHS = {
    "greenhouse": "backend/evidence/greenhouse-phase-a-readiness.json",
    "lever": "backend/evidence/lever-pilot-readiness.json",
    "ashby": "backend/evidence/ashby-certification-dossier.json",
}
ADAPTER_INTEGRATION_PATHS = {
    "ashby": ("backend/app/services/ashby_profile_aliases.py",),
    "smartrecruiters": (
        "backend/app/services/smartrecruiters_challenge.py",
        "backend/app/services/smartrecruiters_contract.py",
    ),
    "workday": (
        "backend/app/services/workday_challenge.py",
        "backend/app/services/workday_popup_boundaries.py",
        "backend/app/services/workday_port_integration.py",
    ),
}
COMMON_SOURCE_PATHS = (
    "backend/app/services/ats_base.py",
    "backend/app/services/ats_registry.py",
)
SOURCE_PATHS = {
    name: (
        f"backend/app/services/ats_{name}.py",
        *COMMON_SOURCE_PATHS,
        *ADAPTER_INTEGRATION_PATHS.get(name, ()),
    )
    for name in ADAPTERS
}
COMMON_FIXTURE_PATHS = (
    "backend/tests/test_ats_maturity.py",
    "backend/tests/test_autonomy_release_contract.py",
)


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _digest_paths(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    seen = False
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if not path.is_file():
            raise ValueError(f"missing digest input: {path}")
        seen = True
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    if not seen:
        raise ValueError("digest input set is empty")
    return digest.hexdigest()


def _fixture_paths(root: Path, adapter: str) -> list[Path]:
    adapter_paths = list((root / "backend/tests").glob(f"test_{adapter}*.py"))
    if not adapter_paths:
        raise ValueError(f"no fixture/regression tests found for {adapter}")
    return [
        *adapter_paths,
        *(root / item for item in COMMON_FIXTURE_PATHS),
    ]


def _manifest_map() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    manifest = ats_certification_manifest()
    adapters = {
        str(item.get("name") or ""): item
        for item in manifest.get("adapters", [])
        if isinstance(item, dict)
    }
    return adapters, manifest


def _greenhouse_metrics(data: Mapping[str, Any]) -> dict[str, Any]:
    gates = data.get("gates") if isinstance(data.get("gates"), Mapping) else {}
    return {
        "supervised_confirmed_count": int(data.get("supervised_confirmed_count") or 0),
        "retained_dry_run_count": int(data.get("qualifying_dry_run_count") or 0),
        "distinct_target_count": int(data.get("distinct_dry_run_employer_count") or 0),
        "explicit_region_coverage_count": 0,
        "durable_archive_verification_present": False,
        "manual_boundary_verification_present": False,
        "zero_false_submissions": int(data.get("false_submitted_count") or 0) == 0,
        "zero_duplicate_submissions": int(data.get("duplicate_submission_count") or 0) == 0,
        "zero_uncertain_status_violations": int(data.get("uncertain_status_violation_count") or 0) == 0,
        "final_submit_clicked": False,
        "independent_success_review_complete": bool(gates.get("all_success_evidence_independently_reviewed")),
        "explicit_promotion_approval": bool(gates.get("explicit_release_approval_reference")),
        "ten_supervised_confirmed_submissions": bool(gates.get("ten_supervised_confirmed_submissions")),
    }


def _lever_metrics(data: Mapping[str, Any]) -> dict[str, Any]:
    summary = data.get("summary") if isinstance(data.get("summary"), Mapping) else {}
    gates = summary.get("gates") if isinstance(summary.get("gates"), Mapping) else {}
    return {
        "supervised_confirmed_count": int(summary.get("supervised_confirmed_count") or 0),
        "retained_dry_run_count": int(summary.get("qualifying_dry_run_count") or 0),
        "distinct_target_count": int(summary.get("distinct_site_count") or 0),
        "explicit_region_coverage_count": len(summary.get("regions_covered") or []),
        "durable_archive_verification_present": bool(
            gates.get("all_qualifying_phase_a_records_have_durable_external_archives")
        ),
        "manual_boundary_verification_present": bool(
            int(summary.get("manual_challenge_boundary_count") or 0) > 0
            and int(summary.get("manual_challenge_violation_count") or 0) == 0
        ),
        "zero_false_submissions": _is_explicit_zero(summary, "false_submitted_count"),
        "zero_duplicate_submissions": _is_explicit_zero(summary, "duplicate_submission_count"),
        "zero_uncertain_status_violations": _is_explicit_zero(
            summary, "uncertain_status_violation_count"
        ),
        "final_submit_clicked": False,
        "independent_success_review_complete": bool(gates.get("all_success_evidence_independently_reviewed")),
        "explicit_promotion_approval": bool(gates.get("explicit_separate_promotion_approval")),
        "ten_supervised_confirmed_submissions": bool(gates.get("ten_supervised_confirmed_submissions")),
    }


def _is_explicit_zero(values: Mapping[str, Any], key: str) -> bool:
    """Accept safety evidence only when an explicit nonnegative integer is zero."""
    value = values.get(key)
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0 and value == 0


def _ashby_metrics(data: Mapping[str, Any]) -> dict[str, Any]:
    coverage = data.get("coverage") if isinstance(data.get("coverage"), Mapping) else {}
    safety = data.get("safety") if isinstance(data.get("safety"), Mapping) else {}
    synthetic = (
        data.get("synthetic_live_dry_run")
        if isinstance(data.get("synthetic_live_dry_run"), Mapping)
        else {}
    )
    live = (
        data.get("live_public_form_inspection")
        if isinstance(data.get("live_public_form_inspection"), Mapping)
        else {}
    )
    readiness = data.get("readiness") if isinstance(data.get("readiness"), Mapping) else {}
    return {
        "supervised_confirmed_count": int(safety.get("credited_real_submissions") or 0),
        "retained_dry_run_count": 1 if synthetic.get("passed") is True else 0,
        "distinct_target_count": int(coverage.get("distinct_current_public_targets") or 0),
        "explicit_region_coverage_count": 0,
        "durable_archive_verification_present": False,
        "manual_boundary_verification_present": bool(
            coverage.get("manual_challenge_handoff") is True
            and coverage.get("resumable_handoff") is True
        ),
        "zero_false_submissions": int(safety.get("false_submitted_records") or 0) == 0,
        "zero_duplicate_submissions": (
            int(synthetic.get("duplicate_targets_within_lane") or 0) == 0
            and int(live.get("duplicate_targets_within_lane") or 0) == 0
        ),
        "zero_uncertain_status_violations": int(safety.get("uncertain_outcomes_credited_as_submitted") or 0) == 0,
        "final_submit_clicked": bool(safety.get("final_submit_clicked")),
        "independent_success_review_complete": False,
        "explicit_promotion_approval": False,
        "ten_supervised_confirmed_submissions": False,
        "promotion_blockers": list(readiness.get("promotion_blockers") or []),
    }


def _metrics_for(adapter: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    if adapter == "greenhouse":
        return _greenhouse_metrics(evidence)
    if adapter == "lever":
        return _lever_metrics(evidence)
    if adapter == "ashby":
        return _ashby_metrics(evidence)
    return {
        "supervised_confirmed_count": 0,
        "retained_dry_run_count": 0,
        "distinct_target_count": 0,
        "explicit_region_coverage_count": 0,
        "durable_archive_verification_present": False,
        "manual_boundary_verification_present": True,
        "zero_false_submissions": True,
        "zero_duplicate_submissions": True,
        "zero_uncertain_status_violations": True,
        "final_submit_clicked": False,
        "independent_success_review_complete": False,
        "explicit_promotion_approval": False,
        "ten_supervised_confirmed_submissions": False,
    }


def _ranking_key(metrics: Mapping[str, Any]) -> tuple[int, int, int, int, int, int]:
    return (
        int(metrics.get("supervised_confirmed_count") or 0),
        int(metrics.get("retained_dry_run_count") or 0),
        int(metrics.get("distinct_target_count") or 0),
        int(metrics.get("explicit_region_coverage_count") or 0),
        int(metrics.get("durable_archive_verification_present") is True),
        int(metrics.get("manual_boundary_verification_present") is True),
    )


def _candidate_eligible(maturity: str, metrics: Mapping[str, Any]) -> bool:
    return bool(
        maturity == "dry_run"
        and metrics.get("zero_false_submissions") is True
        and metrics.get("zero_duplicate_submissions") is True
        and metrics.get("zero_uncertain_status_violations") is True
        and metrics.get("final_submit_clicked") is False
    )


def build_phase4_candidate_gate(
    *,
    verification_commit: str,
    root: Path | None = None,
) -> dict[str, Any]:
    verification_commit = str(verification_commit or "").strip().lower()
    if not COMMIT_RE.fullmatch(verification_commit):
        raise ValueError("verification_commit must be an exact 40-character git SHA")

    repository_root = root or _root()
    freeze = _load_json(repository_root / FREEZE_PATH)
    manifest_by_name, ats = _manifest_map()
    operations = operations_readiness_manifest()

    frozen_adapters = freeze.get("adapters") if isinstance(freeze.get("adapters"), Mapping) else {}
    rows: list[dict[str, Any]] = []
    drift: list[str] = []

    for adapter in ADAPTERS:
        current = manifest_by_name.get(adapter)
        if not isinstance(current, Mapping):
            drift.append(f"{adapter}:missing_manifest")
            continue
        frozen = frozen_adapters.get(adapter)
        if not isinstance(frozen, Mapping):
            drift.append(f"{adapter}:missing_freeze")
            continue

        version = str(current.get("version") or "")
        maturity = str(current.get("maturity") or "")
        if version != str(frozen.get("version") or ""):
            drift.append(f"{adapter}:version_drift")
        if maturity != str(frozen.get("maturity") or ""):
            drift.append(f"{adapter}:maturity_drift")

        source_files = [repository_root / item for item in SOURCE_PATHS[adapter]]
        fixture_files = _fixture_paths(repository_root, adapter)
        evidence_path = EVIDENCE_PATHS.get(adapter)
        evidence: dict[str, Any] = {}
        retained_evidence_sha256: str | None = None
        if evidence_path:
            evidence_file = repository_root / evidence_path
            evidence = _load_json(evidence_file)
            retained_evidence_sha256 = hashlib.sha256(evidence_file.read_bytes()).hexdigest()

        metrics = _metrics_for(adapter, evidence)
        live_evidence = current.get("live_certification") or {}
        digests = {
            "adapter_source_sha256": _digest_paths(repository_root, source_files),
            "fixture_regression_sha256": _digest_paths(repository_root, fixture_files),
            "retained_evidence_sha256": retained_evidence_sha256,
            "manifest_live_evidence_sha256": _canonical_sha256(live_evidence),
        }
        frozen_digests = frozen.get("digests")
        if not isinstance(frozen_digests, Mapping):
            drift.append(f"{adapter}:missing_frozen_digests")
        else:
            for digest_name, computed_digest in digests.items():
                if (
                    digest_name not in frozen_digests
                    or frozen_digests.get(digest_name) != computed_digest
                ):
                    drift.append(f"{adapter}:{digest_name}_drift")

        row = {
            "adapter": adapter,
            "version": version,
            "maturity": maturity,
            "candidate_eligible": _candidate_eligible(maturity, metrics),
            "ranking_key": list(_ranking_key(metrics)),
            "metrics": metrics,
            "digests": digests,
            "sources": {
                "adapter_source_paths": [item.relative_to(repository_root).as_posix() for item in source_files],
                "fixture_regression_paths": [item.relative_to(repository_root).as_posix() for item in sorted(fixture_files)],
                "retained_evidence_path": evidence_path,
            },
        }
        rows.append(row)

    eligible = [row for row in rows if row.get("candidate_eligible") is True]
    ranked = sorted(
        eligible,
        key=lambda row: (tuple(row["ranking_key"]), row["adapter"]),
        reverse=True,
    )
    selected = ranked[0] if ranked else None
    frozen_candidate = (
        freeze.get("candidate") if isinstance(freeze.get("candidate"), Mapping) else {}
    )
    expected_candidate = str(frozen_candidate.get("adapter") or "")
    if selected is None:
        drift.append("candidate:none_eligible")
    elif selected.get("adapter") != expected_candidate:
        drift.append(
            f"candidate:selection_drift:{selected.get('adapter')}!=${expected_candidate}"
        )

    candidate_name = str(selected.get("adapter") if selected else "")
    candidate_metrics = dict(selected.get("metrics") or {}) if selected else {}
    supervised_blockers: list[str] = []
    if candidate_metrics.get("ten_supervised_confirmed_submissions") is not True:
        supervised_blockers.append("ten_distinct_supervised_confirmed_submissions_missing")
    if candidate_metrics.get("independent_success_review_complete") is not True:
        supervised_blockers.append("independent_success_review_missing")
    if candidate_metrics.get("explicit_promotion_approval") is not True:
        supervised_blockers.append("separate_explicit_promotion_approval_missing")
    supervised_blockers.append("signed_exact_commit_autonomy_release_manifest_missing")
    supervised_blockers.extend(f"shadow:{name}:missing" for name in REQUIRED_SHADOW_CHECKS)

    autonomous_adapters = list(ats.get("autonomous_adapters") or [])
    runtime_safe = bool(
        operations.get("real_submission_enabled") is False
        and operations.get("autopilot_enabled") is False
        and not autonomous_adapters
        and all(row.get("maturity") != "certified_autonomous" for row in rows)
    )
    gate_passed = bool(
        not drift
        and candidate_name == expected_candidate == "lever"
        and runtime_safe
        and candidate_metrics.get("supervised_confirmed_count") == 0
        and supervised_blockers
    )

    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "gate_version": PHASE4_GATE_VERSION,
        "verification_commit": verification_commit,
        "freeze_source_commit": str(freeze.get("freeze_source_commit") or ""),
        "gate_passed": gate_passed,
        "candidate": {
            "adapter": candidate_name or None,
            "selection_scope": "unattended_pilot_preparation_only",
            "promotion_authorized": False,
            "unattended_submission_allowed": False,
            "certified_autonomous": False,
            "ranking_key": list(selected.get("ranking_key") or []) if selected else [],
            "metrics": candidate_metrics,
            "remaining_blockers": supervised_blockers,
        },
        "ranking": [
            {
                "position": index + 1,
                "adapter": row["adapter"],
                "ranking_key": row["ranking_key"],
                "metrics": row["metrics"],
            }
            for index, row in enumerate(ranked)
        ],
        "adapter_freeze": rows,
        "remaining_supervised_only_boundaries": freeze.get("remaining_supervised_only_boundaries") or {},
        "autonomy_contract_thresholds": {
            "minimum_supervised_attempts": MIN_RELIABILITY_ATTEMPTS,
            "minimum_success_rate": MIN_SUCCESS_RATE,
            "required_shadow_checks": list(REQUIRED_SHADOW_CHECKS),
        },
        "runtime_safety": {
            "real_submission_enabled": bool(operations.get("real_submission_enabled")),
            "autopilot_enabled": bool(operations.get("autopilot_enabled")),
            "autonomous_adapters": autonomous_adapters,
            "safe": runtime_safe,
        },
        "drift": drift,
        "freeze_policy": freeze.get("freeze_policy") or {},
    }
    payload["gate_sha256"] = _canonical_sha256(payload)
    return payload
