"""Read-only evidence gates for roadmap Days 12 through 22.

The evaluator converts retained Lever, Lever Phase B launch, and Greenhouse
snapshots into one deterministic checkpoint report. It never opens a browser,
issues an approval, submits an application, or promotes an adapter.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

LEVER_PHASE_A_GATES = (
    "thirty_qualifying_dry_runs",
    "thirty_distinct_lever_sites",
    "global_and_eu_hosts_covered",
    "all_phase_a_records_have_successful_matching_inspection",
    "all_manual_challenges_remain_needs_review",
)
LEVER_PHASE_B_GATES = (
    "ten_supervised_confirmed_submissions",
    "zero_false_submitted_records",
    "zero_duplicate_submissions",
    "all_uncertain_outcomes_remain_uncertain",
    "all_success_evidence_independently_reviewed",
    "all_evidence_hashes_match_consumed_approvals",
)
GREENHOUSE_CERTIFICATION_GATES = (
    "thirty_qualifying_dry_runs",
    "thirty_distinct_employers",
    "ten_supervised_confirmed_submissions",
    "zero_false_submitted_records",
    "zero_duplicate_submissions",
    "all_uncertain_outcomes_remain_uncertain",
    "all_success_evidence_independently_reviewed",
    "explicit_release_approval_reference",
)
LEVER_PHASE_B_LAUNCH_SCHEMA_VERSION = "1.1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_Pathish = Union[str, Path]


def _lever_summary(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    return dict(readiness.get("summary") or {})


def _greenhouse_summary(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    nested = readiness.get("summary")
    return dict(nested if isinstance(nested, Mapping) else readiness)


def _checkpoint(
    day: int, title: str, passed: bool, facts: Dict[str, Any], blockers: list[str]
) -> Dict[str, Any]:
    return {
        "day": day,
        "title": title,
        "status": "complete" if passed else "blocked_by_evidence_or_user_gate",
        "passed": passed,
        "facts": facts,
        "blockers": [] if passed else blockers,
    }


def _application_id(record: Mapping[str, Any]) -> str:
    return str(record.get("application_id") or "").strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _valid_sha256(value: Any) -> Optional[str]:
    digest = str(value or "").strip().lower()
    return digest if _SHA256_RE.fullmatch(digest) else None


def _retained_dossier_is_valid(
    application_id: str,
    dossier_claim: Mapping[str, Any],
    artifact_root: Optional[_Pathish],
) -> tuple[bool, str]:
    declared_dossier_sha = _valid_sha256(dossier_claim.get("dossier_sha256"))
    declared_artifact_sha = _valid_sha256(dossier_claim.get("artifact_sha256"))
    artifact_path = str(dossier_claim.get("artifact_path") or "").strip()

    if dossier_claim.get("read_only") is not True:
        return False, "manifest_dossier_not_read_only"
    if dossier_claim.get("one_time_approval_required") is not True:
        return False, "manifest_one_time_approval_not_required"
    if declared_dossier_sha is None:
        return False, "manifest_dossier_sha256_invalid"
    if declared_artifact_sha is None:
        return False, "manifest_artifact_sha256_invalid"
    if not artifact_path:
        return False, "manifest_artifact_path_missing"
    if artifact_root is None:
        return False, "artifact_root_missing"

    root = Path(artifact_root).resolve()
    relative_path = Path(artifact_path)
    if relative_path.is_absolute():
        return False, "artifact_path_must_be_relative"

    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return False, "artifact_path_escapes_root"

    try:
        artifact_bytes = candidate.read_bytes()
    except OSError:
        return False, "artifact_unreadable"

    computed_artifact_sha = hashlib.sha256(artifact_bytes).hexdigest()
    if not hmac.compare_digest(computed_artifact_sha, declared_artifact_sha):
        return False, "artifact_sha256_mismatch"

    try:
        artifact = json.loads(artifact_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, "artifact_json_invalid"
    if not isinstance(artifact, Mapping):
        return False, "artifact_json_not_object"

    artifact_application_id = str(artifact.get("application_id") or "").strip()
    if not hmac.compare_digest(artifact_application_id, application_id):
        return False, "artifact_application_id_mismatch"
    if artifact.get("read_only") is not True:
        return False, "artifact_not_read_only"
    if artifact.get("scope") != "lever_supervised_phase_b_candidate":
        return False, "artifact_scope_mismatch"
    if artifact.get("selection_policy") != "user_selected_exact_application_no_ranking":
        return False, "artifact_selection_policy_mismatch"

    target = artifact.get("target")
    if not isinstance(target, Mapping) or str(target.get("platform") or "").lower() != "lever":
        return False, "artifact_platform_mismatch"
    kill_switches = artifact.get("kill_switches")
    if not isinstance(kill_switches, Mapping) or kill_switches.get(
        "one_time_approval_required"
    ) is not True:
        return False, "artifact_one_time_approval_not_required"

    artifact_dossier_sha = _valid_sha256(artifact.get("dossier_sha256"))
    if artifact_dossier_sha is None:
        return False, "artifact_dossier_sha256_invalid"

    canonical_dossier = dict(artifact)
    canonical_dossier.pop("dossier_sha256", None)
    canonical_dossier.pop("download_filename", None)
    computed_dossier_sha = _canonical_sha256(canonical_dossier)
    if not hmac.compare_digest(computed_dossier_sha, artifact_dossier_sha):
        return False, "artifact_dossier_sha256_mismatch"
    if not hmac.compare_digest(computed_dossier_sha, declared_dossier_sha):
        return False, "manifest_dossier_sha256_mismatch"

    download_filename = str(artifact.get("download_filename") or "").strip()
    if download_filename and download_filename != candidate.name:
        return False, "artifact_download_filename_mismatch"

    return True, "verified"


def _lever_launch_facts(
    evidence: Optional[Mapping[str, Any]],
    artifact_root: Optional[_Pathish] = None,
) -> Dict[str, Any]:
    payload = dict(evidence or {})
    raw_records = payload.get("applications") or []
    records = [dict(item) for item in raw_records if isinstance(item, Mapping)]

    selected: set[str] = set()
    dossiers: set[str] = set()
    previews: set[str] = set()
    ready: set[str] = set()
    seen_application_ids: set[str] = set()
    dossier_validation_errors: list[Dict[str, str]] = []
    malformed = len(raw_records) - len(records) if isinstance(raw_records, list) else 1
    duplicates = 0
    schema_valid = payload.get("schema_version") == LEVER_PHASE_B_LAUNCH_SCHEMA_VERSION

    for record in records:
        application_id = _application_id(record)
        if not application_id or str(record.get("platform") or "").lower() != "lever":
            malformed += 1
            continue
        if application_id in seen_application_ids:
            duplicates += 1
            continue
        seen_application_ids.add(application_id)

        selection_reference = str(record.get("selection_reference") or "").strip()
        selected_ok = record.get("selected_by_user") is True and bool(selection_reference)
        if selected_ok:
            selected.add(application_id)

        dossier_ok = False
        dossier = record.get("dossier")
        if isinstance(dossier, Mapping):
            dossier_ok, reason = _retained_dossier_is_valid(
                application_id, dossier, artifact_root
            )
        else:
            reason = "manifest_dossier_missing"
        if dossier_ok:
            dossiers.add(application_id)
        else:
            dossier_validation_errors.append(
                {"application_id": application_id, "reason": reason}
            )

        preview = record.get("dry_preview")
        preview_ok = bool(
            isinstance(preview, Mapping)
            and preview.get("passed") is True
            and preview.get("final_submit_clicked") is False
            and preview.get("outcome") == "ready_to_submit"
        )
        if preview_ok:
            previews.add(application_id)

        if selected_ok and dossier_ok and preview_ok:
            ready.add(application_id)

    return {
        "selected_application_count": len(selected),
        "approval_dossier_count": len(dossiers),
        "dry_preview_count": len(previews),
        "ready_application_count": len(ready),
        "ready_application_ids": sorted(ready),
        "malformed_record_count": malformed,
        "duplicate_application_count": duplicates,
        "invalid_dossier_count": len(dossier_validation_errors),
        "dossier_validation_errors": dossier_validation_errors,
        "source_schema_version": payload.get("schema_version"),
        "source_schema_valid": schema_valid,
    }


def build_day_12_22_report(
    lever_readiness: Mapping[str, Any],
    greenhouse_readiness: Mapping[str, Any],
    lever_phase_b_launch: Optional[Mapping[str, Any]] = None,
    *,
    lever_phase_b_artifact_root: Optional[_Pathish] = None,
) -> Dict[str, Any]:
    """Build the Days 12--22 report solely from retained evidence."""

    lever = _lever_summary(lever_readiness)
    lever_gates = dict(lever.get("gates") or {})
    dry_runs = int(lever.get("qualifying_dry_run_count") or 0)
    sites = int(lever.get("distinct_site_count") or 0)
    regions = sorted(str(item) for item in lever.get("regions_covered") or [])
    confirmed = int(lever.get("supervised_confirmed_count") or 0)
    phase_a = all(lever_gates.get(name) is True for name in LEVER_PHASE_A_GATES)
    phase_b = all(lever_gates.get(name) is True for name in LEVER_PHASE_B_GATES)

    checkpoints = []
    day12_passed = dry_runs >= 20 and sites >= 20
    checkpoints.append(
        _checkpoint(
            12,
            "Lever dry runs 16 through 20",
            day12_passed,
            {
                "qualifying_dry_runs": dry_runs,
                "target": 20,
                "distinct_sites": sites,
                "regions_covered": regions,
            },
            [
                *(
                    [f"retain and verify {20 - dry_runs} more qualifying dry runs"]
                    if dry_runs < 20
                    else []
                ),
                *(
                    [f"retain and verify {20 - sites} more distinct Lever sites"]
                    if sites < 20
                    else []
                ),
            ],
        )
    )

    challenge_encounters = int(lever.get("manual_challenge_encounter_count") or 0)
    challenge_boundaries = int(lever.get("manual_challenge_boundary_count") or 0)
    challenge_violations = int(lever.get("manual_challenge_violation_count") or 0)
    challenge_safe = bool(
        lever_gates.get("all_manual_challenges_remain_needs_review") is True
        and challenge_violations == 0
        and challenge_boundaries == challenge_encounters
    )
    day13_passed = dry_runs >= 25 and sites >= 25 and challenge_safe
    checkpoints.append(
        _checkpoint(
            13,
            "Lever dry runs 21 through 25 and challenge boundaries",
            day13_passed,
            {
                "qualifying_dry_runs": dry_runs,
                "target": 25,
                "distinct_sites": sites,
                "regions_covered": regions,
                "manual_challenge_encounters": challenge_encounters,
                "manual_challenge_boundaries": challenge_boundaries,
                "manual_challenge_violations": challenge_violations,
                "all_manual_challenges_remain_needs_review": challenge_safe,
            },
            [
                *(
                    [f"retain and verify {25 - dry_runs} more qualifying dry runs"]
                    if dry_runs < 25
                    else []
                ),
                *(
                    [f"retain and verify {25 - sites} more distinct Lever sites"]
                    if sites < 25
                    else []
                ),
                *(
                    [
                        "resolve every CAPTCHA, MFA, login, or anti-bot outcome to "
                        "manual_challenge_handoff + needs_review"
                    ]
                    if not challenge_safe
                    else []
                ),
            ],
        )
    )

    checkpoints.append(
        _checkpoint(
            14,
            "Lever Phase A certification",
            phase_a,
            {
                "qualifying_dry_runs": dry_runs,
                "distinct_sites": sites,
                "regions_covered": regions,
                "gate_state": {
                    name: lever_gates.get(name) is True for name in LEVER_PHASE_A_GATES
                },
            },
            [name for name in LEVER_PHASE_A_GATES if lever_gates.get(name) is not True],
        )
    )

    launch = _lever_launch_facts(
        lever_phase_b_launch, artifact_root=lever_phase_b_artifact_root
    )
    day15_integrity_clean = bool(
        launch["source_schema_valid"]
        and launch["malformed_record_count"] == 0
        and launch["duplicate_application_count"] == 0
        and launch["invalid_dossier_count"] == 0
    )
    day15_passed = (
        phase_a and day15_integrity_clean and launch["ready_application_count"] >= 2
    )
    checkpoints.append(
        _checkpoint(
            15,
            "Lever Phase B launch dossier",
            day15_passed,
            {
                "phase_a_complete": phase_a,
                **launch,
                "target_ready_applications": 2,
            },
            (["complete Lever Phase A"] if not phase_a else [])
            + (
                [
                    f"use Lever Phase B launch schema "
                    f"{LEVER_PHASE_B_LAUNCH_SCHEMA_VERSION}"
                ]
                if not launch["source_schema_valid"]
                else []
            )
            + (
                [
                    "retain two exact user-selected Lever applications with "
                    "byte-verified, application-bound read-only dossiers and "
                    "successful no-submit dry previews"
                ]
                if launch["ready_application_count"] < 2
                else []
            )
            + (
                ["remove or repair malformed Lever Phase B launch evidence records"]
                if launch["malformed_record_count"]
                else []
            )
            + (
                ["remove duplicate application records from Lever Phase B launch evidence"]
                if launch["duplicate_application_count"]
                else []
            )
            + (
                ["repair every retained dossier artifact validation failure"]
                if launch["invalid_dossier_count"]
                else []
            ),
        )
    )

    for day, target in ((16, 2), (17, 4), (18, 6), (19, 8), (20, 10)):
        passed = (
            phase_a
            and confirmed >= target
            and all(
                lever_gates.get(name) is True for name in LEVER_PHASE_B_GATES[1:]
            )
        )
        checkpoints.append(
            _checkpoint(
                day,
                f"Lever supervised submissions through {target}",
                passed,
                {
                    "phase_a_complete": phase_a,
                    "safe_confirmed_submissions": confirmed,
                    "target": target,
                    "phase_b_safety_gates": {
                        name: lever_gates.get(name) is True
                        for name in LEVER_PHASE_B_GATES[1:]
                    },
                },
                (["complete Lever Phase A"] if not phase_a else [])
                + (
                    [
                        f"obtain exact user approvals and independently verify "
                        f"{target - confirmed} more distinct submissions"
                    ]
                    if confirmed < target
                    else []
                )
                + [
                    name
                    for name in LEVER_PHASE_B_GATES[1:]
                    if lever_gates.get(name) is not True
                ],
            )
        )

    promotion_passed = (
        phase_a
        and phase_b
        and lever.get("promotion_ready") is True
        and lever_gates.get("explicit_separate_promotion_approval") is True
    )
    checkpoints.append(
        _checkpoint(
            21,
            "Lever promotion decision",
            promotion_passed,
            {
                "phase_a_complete": phase_a,
                "phase_b_complete": phase_b,
                "canonical_maturity": lever.get("canonical_maturity"),
                "promotion_ready": lever.get("promotion_ready") is True,
                "explicit_promotion_approval": lever_gates.get(
                    "explicit_separate_promotion_approval"
                )
                is True,
            },
            (["complete Lever Phase A"] if not phase_a else [])
            + (["complete all Lever Phase B evidence gates"] if not phase_b else [])
            + (
                ["canonical readiness must report promotion_ready=true"]
                if lever.get("promotion_ready") is not True
                else []
            )
            + (
                ["owner approval and a separate maturity-promotion change are required"]
                if lever_gates.get("explicit_separate_promotion_approval") is not True
                else []
            ),
        )
    )

    greenhouse = _greenhouse_summary(greenhouse_readiness)
    greenhouse_gates = dict(greenhouse.get("gates") or {})
    greenhouse_gate_state = {
        name: greenhouse_gates.get(name) is True
        for name in GREENHOUSE_CERTIFICATION_GATES
    }
    greenhouse_ready = greenhouse.get("human_reviewed_submit_ready") is True
    greenhouse_backlog = [
        name for name, passed in greenhouse_gate_state.items() if not passed
    ]
    if not greenhouse_ready:
        greenhouse_backlog.append("human_reviewed_submit_ready")
    greenhouse_passed = all(greenhouse_gate_state.values()) and greenhouse_ready
    greenhouse_gap_matrix = {
        "phase_a_qualifying_dry_runs": int(
            greenhouse.get("qualifying_dry_run_count") or 0
        ),
        "phase_a_distinct_employers": int(
            greenhouse.get("distinct_dry_run_employer_count") or 0
        ),
        "phase_b_confirmed_submissions": int(
            greenhouse.get("supervised_confirmed_count") or 0
        ),
        "gate_state": greenhouse_gate_state,
        "false_submission_protection": greenhouse_gate_state[
            "zero_false_submitted_records"
        ],
        "duplicate_protection": greenhouse_gate_state["zero_duplicate_submissions"],
        "uncertain_state_protection": greenhouse_gate_state[
            "all_uncertain_outcomes_remain_uncertain"
        ],
        "independent_evidence_review": greenhouse_gate_state[
            "all_success_evidence_independently_reviewed"
        ],
    }
    checkpoints.append(
        _checkpoint(
            22,
            "Greenhouse certification gap analysis",
            greenhouse_passed,
            {
                "gate_matrix": greenhouse_gap_matrix,
                "exact_backlog": greenhouse_backlog,
                "human_reviewed_submit_ready": greenhouse_ready,
            },
            greenhouse_backlog,
        )
    )

    return {
        "schema_version": "1.1",
        "scope": "roadmap_days_12_through_22",
        "mode": "read_only_evidence_evaluation",
        "checkpoints": checkpoints,
        "summary": {
            "complete_days": [item["day"] for item in checkpoints if item["passed"]],
            "blocked_days": [item["day"] for item in checkpoints if not item["passed"]],
            "next_action": next(
                (item["blockers"][0] for item in checkpoints if item["blockers"]), None
            ),
        },
        "safety": {
            "network_contacted": False,
            "browser_opened": False,
            "approval_issued": False,
            "submission_queued": False,
            "final_submit_clicked": False,
            "maturity_promoted": False,
        },
    }


__all__ = [
    "GREENHOUSE_CERTIFICATION_GATES",
    "LEVER_PHASE_A_GATES",
    "LEVER_PHASE_B_GATES",
    "LEVER_PHASE_B_LAUNCH_SCHEMA_VERSION",
    "build_day_12_22_report",
]
