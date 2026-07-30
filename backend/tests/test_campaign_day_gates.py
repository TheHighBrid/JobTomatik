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


def test_owner_report_is_visible_but_does_not_replace_ledger_evidence():
    reported = {
        "candidate_lever_sites": 30,
        "report_reference": "owner-report-2026-07-30",
        "reported_at": "2026-07-30",
        "source": "repository_owner_chat_report",
        "distinct_lever_sites": 19,
        "supervised_confirmed_submissions": 19,
        "independently_reviewed_submissions": 19,
    }
    report = build_day_12_22_report(_lever(), _greenhouse(), reported)
    day20 = next(item for item in report["checkpoints"] if item["day"] == 20)
    assert day20["passed"] is False
    assert day20["facts"]["operator_reported_confirmed_submissions"] == 19
    assert day20["facts"]["reported_records_pending_ledger_reconciliation"] == 19
    assert report["reported_progress"]["certification_effect"].startswith(
        "informational"
    )
    assert report["reported_progress"]["valid"] is True


def test_malformed_owner_report_fails_closed_as_informational_only():
    report = build_day_12_22_report(
        _lever(),
        _greenhouse(),
        {
            "candidate_lever_sites": 30,
            "distinct_lever_sites": 31,
            "supervised_confirmed_submissions": 2,
            "independently_reviewed_submissions": 3,
        },
    )
    progress = report["reported_progress"]
    assert progress["valid"] is False
    assert (
        "distinct_lever_sites_cannot_exceed_candidate_lever_sites"
        in progress["validation_issues"]
    )
    assert (
        "independently_reviewed_submissions_cannot_exceed_confirmed_submissions"
        in progress["validation_issues"]
    )


def test_day_15_can_complete_from_retained_dossier_counts():
    lever = _lever(
        30,
        30,
        0,
        {
            "thirty_qualifying_dry_runs": True,
            "thirty_distinct_lever_sites": True,
            "global_and_eu_hosts_covered": True,
            "all_phase_a_records_have_successful_matching_inspection": True,
        },
    )
    lever["summary"].update(
        selected_application_count=2, approval_dossier_count=2, dry_preview_count=2
    )
    report = build_day_12_22_report(lever, _greenhouse())
    day15 = next(item for item in report["checkpoints"] if item["day"] == 15)
    assert day15["passed"] is True
