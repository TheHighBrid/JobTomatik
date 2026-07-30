"""Read-only evidence gates for roadmap Days 12 through 22.

The evaluator converts retained Lever, Lever Phase B launch, and Greenhouse
snapshots into one deterministic checkpoint report. It never opens a browser,
issues an approval, submits an application, or promotes an adapter.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional

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
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _lever_launch_facts(evidence: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    payload = dict(evidence or {})
    raw_records = payload.get("applications") or []
    records = [dict(item) for item in raw_records if isinstance(item, Mapping)]

    selected: set[str] = set()
    dossiers: set[str] = set()
    previews: set[str] = set()
    malformed = 0

    for record in records:
        application_id = _application_id(record)
        if not application_id or str(record.get("platform") or "").lower() != "lever":
            malformed += 1
            continue

        selection_reference = str(record.get("selection_reference") or "").strip()
        if record.get("selected_by_user") is True and selection_reference:
            selected.add(application_id)

        dossier = record.get("dossier")
        if isinstance(dossier, Mapping):
            digest = str(dossier.get("dossier_sha256") or "").strip().lower()
            if (
                dossier.get("read_only") is True
                and dossier.get("one_time_approval_required") is True
                and _SHA256_RE.fullmatch(digest)
            ):
                dossiers.add(application_id)

        preview = record.get("dry_preview")
        if isinstance(preview, Mapping):
            if (
                preview.get("passed") is True
                and preview.get("final_submit_clicked") is False
                and preview.get("outcome") == "ready_to_submit"
            ):
                previews.add(application_id)

    ready = selected & dossiers & previews
    return {
        "selected_application_count": len(selected),
        "approval_dossier_count": len(dossiers),
        "dry_preview_count": len(previews),
        "ready_application_count": len(ready),
        "ready_application_ids": sorted(ready),
        "malformed_record_count": malformed,
        "source_schema_version": payload.get("schema_version"),
    }


def build_day_12_22_report(
    lever_readiness: Mapping[str, Any],
    greenhouse_readiness: Mapping[str, Any],
    lever_phase_b_launch: Optional[Mapping[str, Any]] = None,
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

    launch = _lever_launch_facts(lever_phase_b_launch)
    day15_passed = phase_a and launch["ready_application_count"] >= 2
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
                    "retain two exact user-selected Lever applications with valid "
                    "read-only dossier hashes and successful no-submit dry previews"
                ]
                if launch["ready_application_count"] < 2
                else []
            )
            + (
                ["remove or repair malformed Lever Phase B launch evidence records"]
                if launch["malformed_record_count"]
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
    "build_day_12_22_report",
]
