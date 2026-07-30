from __future__ import annotations

import csv

from app.services.lever_readiness_hardening import harden_lever_readiness


FIELDNAMES = [
    "run_id",
    "site",
    "posting_id",
    "region",
    "handoff_reason",
    "pre_submit_state",
    "final_status",
    "official_posting_inspection_passed",
]


def _write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def _readiness():
    return {
        "summary": {
            "platform": "lever",
            "canonical_maturity": "dry_run",
            "gates": {"explicit_separate_promotion_approval": False},
        }
    }


def test_manual_challenge_gate_fails_when_outcome_escapes_needs_review(tmp_path):
    baseline = tmp_path / "phase-a.csv"
    _write(
        baseline,
        [
            {
                "run_id": "safe-captcha",
                "site": "safe",
                "posting_id": "one",
                "region": "global",
                "handoff_reason": "captcha_detected",
                "pre_submit_state": "manual_challenge_handoff",
                "final_status": "needs_review",
                "official_posting_inspection_passed": "false",
            },
            {
                "run_id": "unsafe-captcha",
                "site": "unsafe",
                "posting_id": "two",
                "region": "eu",
                "handoff_reason": "captcha_detected",
                "pre_submit_state": "manual_challenge_handoff",
                "final_status": "dry_run_passed",
                "official_posting_inspection_passed": "false",
            },
        ],
    )

    summary = harden_lever_readiness(
        _readiness(), baseline_path=baseline, ledger_path=None
    )["summary"]

    assert summary["manual_challenge_encounter_count"] == 2
    assert summary["manual_challenge_boundary_count"] == 1
    assert summary["manual_challenge_violation_count"] == 1
    assert summary["gates"]["all_manual_challenges_remain_needs_review"] is False
