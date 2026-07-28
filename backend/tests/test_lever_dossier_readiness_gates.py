from __future__ import annotations

import pytest

from app.services.supervised_pilot_dossier import _pilot_progress


SAFETY_GATES = {
    "zero_false_submitted_records": True,
    "zero_duplicate_submissions": True,
    "all_uncertain_outcomes_remain_uncertain": True,
    "all_success_evidence_independently_reviewed": True,
    "all_evidence_hashes_match_consumed_approvals": True,
}


def _readiness() -> dict[str, object]:
    return {
        "summary": {
            "qualifying_dry_run_count": 30,
            "distinct_site_count": 30,
            "regions_covered": ["global", "eu"],
            "supervised_confirmed_count": 10,
            "raw_supervised_confirmed_count": 10,
            "gates": {
                "thirty_qualifying_dry_runs": True,
                "thirty_distinct_lever_sites": True,
                "global_and_eu_hosts_covered": True,
                "all_phase_a_records_have_successful_matching_inspection": True,
                "ten_supervised_confirmed_submissions": True,
                **SAFETY_GATES,
            },
        }
    }


def test_lever_dossier_marks_complete_only_when_every_gate_passes():
    progress = _pilot_progress(_readiness(), "lever")

    assert progress["phase_a_complete"] is True
    assert progress["phase_b_complete"] is True
    assert progress["phase_b_safety_blockers"] == []


@pytest.mark.parametrize("failed_gate", sorted(SAFETY_GATES))
def test_lever_dossier_rejects_raw_ten_count_when_safety_gate_fails(failed_gate):
    readiness = _readiness()
    readiness["summary"]["gates"][failed_gate] = False

    progress = _pilot_progress(readiness, "lever")

    assert progress["phase_b_confirmed_records"] == 10
    assert progress["phase_b_complete"] is False
    assert failed_gate in progress["phase_b_safety_blockers"]


def test_lever_dossier_does_not_infer_missing_gates_from_counts():
    progress = _pilot_progress(
        {
            "summary": {
                "qualifying_dry_run_count": 30,
                "distinct_site_count": 30,
                "regions_covered": ["global", "eu"],
                "supervised_confirmed_count": 10,
                "gates": {},
            }
        },
        "lever",
    )

    assert progress["phase_a_complete"] is False
    assert progress["phase_b_complete"] is False
