from scripts.certify_lever_pilot_readiness import (
    build_certification_report,
    certify_paths,
)


def _readiness(*, phase_a=False, phase_b=False, duplicate_count=0):
    gates = {
        "thirty_qualifying_dry_runs": phase_a,
        "thirty_distinct_lever_sites": phase_a,
        "global_and_eu_hosts_covered": phase_a,
        "all_phase_a_records_have_successful_matching_inspection": phase_a,
        "ten_supervised_confirmed_submissions": phase_b,
        "zero_false_submitted_records": True,
        "zero_duplicate_submissions": duplicate_count == 0,
        "all_uncertain_outcomes_remain_uncertain": True,
        "all_success_evidence_independently_reviewed": phase_b,
        "all_evidence_hashes_match_consumed_approvals": True,
        "explicit_separate_promotion_approval": False,
    }
    return {
        "summary": {
            "platform": "lever",
            "canonical_maturity": "dry_run",
            "promotion_ready": False,
            "false_submitted_count": 0,
            "duplicate_submission_count": duplicate_count,
            "uncertain_status_violation_count": 0,
            "payload_hash_mismatch_count": 0,
            "gates": gates,
        },
        "baseline_record_count": 30 if phase_a else 0,
        "runtime_record_count": 10 if phase_b else 0,
        "ledger_record_count": (30 if phase_a else 0) + (10 if phase_b else 0),
    }


def test_read_only_certification_passes_without_claiming_threshold_completion():
    report = build_certification_report(_readiness())

    assert report["passed"] is True
    assert report["mode"] == "read_only_evidence_certification"
    assert report["safety"] == {
        "browser_opened": False,
        "network_contacted": False,
        "approval_issued": False,
        "submission_queued": False,
        "final_submit_clicked": False,
        "maturity_promoted": False,
    }
    assert report["readiness"]["summary"]["canonical_maturity"] == "dry_run"
    assert report["readiness"]["summary"]["promotion_ready"] is False


def test_phase_thresholds_are_opt_in_and_fail_closed_when_missing():
    phase_a = build_certification_report(_readiness(), require_phase_a=True)
    phase_b = build_certification_report(_readiness(), require_phase_b=True)

    assert phase_a["passed"] is False
    assert phase_a["checks"]["phase_a_has_thirty_qualifying_dry_runs"] is False
    assert phase_a["checks"]["phase_a_covers_global_and_eu"] is False
    assert (
        phase_a["checks"][
            "phase_a_all_candidates_have_successful_matching_inspection"
        ]
        is False
    )
    assert phase_b["passed"] is False
    assert phase_b["checks"]["phase_b_has_ten_safe_confirmed_submissions"] is False


def test_completed_evidence_still_cannot_self_authorize_promotion():
    report = build_certification_report(
        _readiness(phase_a=True, phase_b=True),
        require_phase_a=True,
        require_phase_b=True,
    )

    assert report["passed"] is True
    assert report["checks"]["promotion_is_not_authorized"] is True
    assert report["checks"]["promotion_ready_is_false"] is True


def test_safety_invariant_violation_fails_certification():
    report = build_certification_report(_readiness(duplicate_count=1))

    assert report["passed"] is False
    assert report["checks"]["zero_duplicate_submissions"] is False


def test_missing_evidence_paths_count_as_zero_without_creating_pilot_success(tmp_path):
    report = certify_paths(
        baseline_path=tmp_path / "missing-phase-a.csv",
        ledger_path=tmp_path / "missing-phase-b.jsonl",
    )

    summary = report["readiness"]["summary"]
    assert report["passed"] is True
    assert summary["qualifying_dry_run_count"] == 0
    assert summary["supervised_confirmed_count"] == 0
    assert summary["promotion_ready"] is False
