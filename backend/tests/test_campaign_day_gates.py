from app.services.campaign_day_gates import build_day_12_22_report


def _lever(dry_runs=0, sites=0, confirmed=0, gates=None):
    return {
        "summary": {
            "qualifying_dry_run_count": dry_runs,
            "distinct_site_count": sites,
            "supervised_confirmed_count": confirmed,
            "regions_covered": ["eu", "global"],
            "canonical_maturity": "dry_run",
            "gates": gates or {},
        }
    }


def _greenhouse():
    return {
        "qualifying_dry_run_count": 30,
        "distinct_dry_run_employer_count": 30,
        "supervised_confirmed_count": 0,
        "gates": {
            "zero_duplicate_submissions": True,
            "all_uncertain_outcomes_remain_uncertain": True,
        },
    }


def test_current_evidence_blocks_external_days_but_completes_gap_analysis():
    report = build_day_12_22_report(_lever(), _greenhouse())
    assert report["summary"]["complete_days"] == [22]
    assert report["summary"]["blocked_days"] == list(range(12, 22))
    assert report["safety"]["final_submit_clicked"] is False
    day22 = report["checkpoints"][-1]
    assert day22["facts"]["exact_backlog"] == [
        "ten_supervised_confirmed_submissions",
        "all_success_evidence_independently_reviewed",
        "explicit_release_approval_reference",
    ]


def test_phase_a_and_phase_b_only_pass_from_all_required_gates():
    gates = {
        "thirty_qualifying_dry_runs": True,
        "thirty_distinct_lever_sites": True,
        "global_and_eu_hosts_covered": True,
        "all_phase_a_records_have_successful_matching_inspection": True,
        "ten_supervised_confirmed_submissions": True,
        "zero_false_submitted_records": True,
        "zero_duplicate_submissions": True,
        "all_uncertain_outcomes_remain_uncertain": True,
        "all_success_evidence_independently_reviewed": True,
        "all_evidence_hashes_match_consumed_approvals": True,
        "explicit_separate_promotion_approval": True,
    }
    report = build_day_12_22_report(_lever(30, 30, 10, gates), _greenhouse())
    assert all(
        day in report["summary"]["complete_days"]
        for day in (12, 13, 14, 16, 17, 18, 19, 20, 21, 22)
    )
    assert 15 in report["summary"]["blocked_days"]


def test_phase_b_cannot_pass_on_count_alone():
    report = build_day_12_22_report(_lever(30, 30, 10, {}), _greenhouse())
    day20 = next(item for item in report["checkpoints"] if item["day"] == 20)
    assert day20["passed"] is False
    assert "all_success_evidence_independently_reviewed" in day20["blockers"]
