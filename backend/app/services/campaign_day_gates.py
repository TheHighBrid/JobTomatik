"""Read-only evidence gates for roadmap Days 12 through 22.

The evaluator converts the retained Lever and Greenhouse readiness snapshots into a
single deterministic checkpoint report.  It deliberately does not run a browser,
issue an approval, submit an application, or promote an adapter.  Evidence work is
reported as blocked until the immutable inputs prove it; calendar pressure can never
turn a missing real-world exercise into a passing gate.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

LEVER_PHASE_A_GATES = (
    "thirty_qualifying_dry_runs",
    "thirty_distinct_lever_sites",
    "global_and_eu_hosts_covered",
    "all_phase_a_records_have_successful_matching_inspection",
)
LEVER_PHASE_B_GATES = (
    "ten_supervised_confirmed_submissions",
    "zero_false_submitted_records",
    "zero_duplicate_submissions",
    "all_uncertain_outcomes_remain_uncertain",
    "all_success_evidence_independently_reviewed",
    "all_evidence_hashes_match_consumed_approvals",
)


def _lever_summary(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    return dict(readiness.get("summary") or {})


def _greenhouse_summary(readiness: Mapping[str, Any]) -> Dict[str, Any]:
    # Greenhouse's retained snapshot predates the nested Lever envelope.
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


def build_day_12_22_report(
    lever_readiness: Mapping[str, Any],
    greenhouse_readiness: Mapping[str, Any],
) -> Dict[str, Any]:
    """Build the Days 12--22 report solely from retained readiness evidence."""

    lever = _lever_summary(lever_readiness)
    lever_gates = dict(lever.get("gates") or {})
    dry_runs = int(lever.get("qualifying_dry_run_count") or 0)
    sites = int(lever.get("distinct_site_count") or 0)
    regions = sorted(str(item) for item in lever.get("regions_covered") or [])
    confirmed = int(lever.get("supervised_confirmed_count") or 0)
    phase_a = all(lever_gates.get(name) is True for name in LEVER_PHASE_A_GATES)
    phase_b = all(lever_gates.get(name) is True for name in LEVER_PHASE_B_GATES)

    checkpoints = []
    for day, target, title in (
        (12, 20, "Lever dry runs 16 through 20"),
        (13, 25, "Lever dry runs 21 through 25 and challenge boundaries"),
    ):
        passed = dry_runs >= target and sites >= target
        checkpoints.append(
            _checkpoint(
                day,
                title,
                passed,
                {
                    "qualifying_dry_runs": dry_runs,
                    "target": target,
                    "distinct_sites": sites,
                    "regions_covered": regions,
                    "manual_challenge_boundaries": int(
                        lever.get("manual_challenge_boundary_count") or 0
                    ),
                },
                [
                    f"retain and verify {max(0, target - dry_runs)} more qualifying distinct-site dry runs"
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

    # A dossier may only become executable after Phase A and explicit applicant
    # selection/policy review.  The readiness ledger intentionally cannot invent it.
    checkpoints.append(
        _checkpoint(
            15,
            "Lever Phase B launch dossier",
            False,
            {
                "phase_a_complete": phase_a,
                "selected_application_count": 0,
                "approval_dossier_count": 0,
            },
            (["complete Lever Phase A"] if not phase_a else [])
            + [
                "user must select real applications and approve truthful profile/legal policies",
                "generate exact one-time approval dossiers for the selected applications",
            ],
        )
    )

    for day, target in ((16, 2), (17, 4), (18, 6), (19, 8), (20, 10)):
        passed = confirmed >= target and all(
            lever_gates.get(name) is True for name in LEVER_PHASE_B_GATES[1:]
        )
        checkpoints.append(
            _checkpoint(
                day,
                f"Lever supervised submissions through {target}",
                passed,
                {
                    "safe_confirmed_submissions": confirmed,
                    "target": target,
                    "phase_b_safety_gates": {
                        name: lever_gates.get(name) is True
                        for name in LEVER_PHASE_B_GATES[1:]
                    },
                },
                [
                    f"obtain exact user approvals and independently verify {max(0, target - confirmed)} more distinct submissions",
                    *[
                        name
                        for name in LEVER_PHASE_B_GATES[1:]
                        if lever_gates.get(name) is not True
                    ],
                ],
            )
        )

    promotion_passed = (
        phase_b and lever_gates.get("explicit_separate_promotion_approval") is True
    )
    checkpoints.append(
        _checkpoint(
            21,
            "Lever promotion decision",
            promotion_passed,
            {
                "phase_b_complete": phase_b,
                "canonical_maturity": lever.get("canonical_maturity"),
                "promotion_ready": lever.get("promotion_ready") is True,
                "explicit_promotion_approval": lever_gates.get(
                    "explicit_separate_promotion_approval"
                )
                is True,
            },
            (["complete all Lever Phase B evidence gates"] if not phase_b else [])
            + [
                "owner approval and a separate maturity-promotion change are required",
            ],
        )
    )

    greenhouse = _greenhouse_summary(greenhouse_readiness)
    greenhouse_gates = dict(greenhouse.get("gates") or {})
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
        "controls": "adapter regression suite required at execution head",
        "duplicate_protection": greenhouse_gates.get("zero_duplicate_submissions")
        is True,
        "uncertain_state_protection": greenhouse_gates.get(
            "all_uncertain_outcomes_remain_uncertain"
        )
        is True,
        "independent_evidence_review": greenhouse_gates.get(
            "all_success_evidence_independently_reviewed"
        )
        is True,
    }
    greenhouse_backlog = [
        name
        for name in (
            "ten_supervised_confirmed_submissions",
            "all_success_evidence_independently_reviewed",
            "explicit_release_approval_reference",
        )
        if greenhouse_gates.get(name) is not True
    ]
    checkpoints.append(
        _checkpoint(
            22,
            "Greenhouse certification gap analysis",
            True,
            {
                "gate_matrix": greenhouse_gap_matrix,
                "exact_backlog": greenhouse_backlog,
                "human_reviewed_submit_ready": greenhouse.get(
                    "human_reviewed_submit_ready"
                )
                is True,
            },
            [],
        )
    )

    return {
        "schema_version": "1.0",
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


__all__ = ["build_day_12_22_report"]
