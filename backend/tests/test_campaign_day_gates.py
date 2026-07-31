import hashlib
import json

from app.services.campaign_day_gates import build_day_12_22_report


LEVER_PHASE_A = {
    "thirty_qualifying_dry_runs": True,
    "thirty_distinct_lever_sites": True,
    "global_and_eu_hosts_covered": True,
    "all_phase_a_records_have_successful_matching_inspection": True,
    "all_manual_challenges_remain_needs_review": True,
}
LEVER_PHASE_B = {
    "ten_supervised_confirmed_submissions": True,
    "zero_false_submitted_records": True,
    "zero_duplicate_submissions": True,
    "all_uncertain_outcomes_remain_uncertain": True,
    "all_success_evidence_independently_reviewed": True,
    "all_evidence_hashes_match_consumed_approvals": True,
}
GREENHOUSE_GATES = {
    "thirty_qualifying_dry_runs": True,
    "thirty_distinct_employers": True,
    "ten_supervised_confirmed_submissions": True,
    "zero_false_submitted_records": True,
    "zero_duplicate_submissions": True,
    "all_uncertain_outcomes_remain_uncertain": True,
    "all_success_evidence_independently_reviewed": True,
    "explicit_release_approval_reference": True,
}


def _lever(dry_runs=0, sites=0, confirmed=0, gates=None, **summary):
    return {
        "summary": {
            "qualifying_dry_run_count": dry_runs,
            "distinct_site_count": sites,
            "supervised_confirmed_count": confirmed,
            "regions_covered": ["eu", "global"],
            "canonical_maturity": "dry_run",
            "promotion_ready": False,
            "manual_challenge_encounter_count": 0,
            "manual_challenge_boundary_count": 0,
            "manual_challenge_violation_count": 0,
            "gates": gates or {},
            **summary,
        }
    }


def _greenhouse(gates=None, ready=False):
    return {
        "qualifying_dry_run_count": 30,
        "distinct_dry_run_employer_count": 30,
        "supervised_confirmed_count": 0,
        "human_reviewed_submit_ready": ready,
        "gates": gates
        or {
            "thirty_qualifying_dry_runs": True,
            "thirty_distinct_employers": True,
            "zero_false_submitted_records": True,
            "zero_duplicate_submissions": True,
            "all_uncertain_outcomes_remain_uncertain": True,
        },
    }


def _canonical_sha256(value):
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_dossier(root, application_id):
    application_id = str(application_id)
    filename = f"lever-phase-b-dossier-application-{application_id}.json"
    dossier = {
        "snapshot_version": "1.2.0",
        "scope": "lever_supervised_phase_b_candidate",
        "selection_policy": "user_selected_exact_application_no_ranking",
        "read_only": True,
        "application_id": application_id,
        "target": {"platform": "lever"},
        "kill_switches": {"one_time_approval_required": True},
    }
    dossier_sha256 = _canonical_sha256(dossier)
    dossier["dossier_sha256"] = dossier_sha256
    dossier["download_filename"] = filename
    artifact_bytes = (json.dumps(dossier, indent=2, sort_keys=True) + "\n").encode()
    (root / filename).write_bytes(artifact_bytes)
    return {
        "artifact_path": filename,
        "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "dossier_sha256": dossier_sha256,
        "read_only": True,
        "one_time_approval_required": True,
    }


def _launch(root, count=2):
    return {
        "schema_version": "1.1",
        "applications": [
            {
                "application_id": str(index + 1),
                "platform": "lever",
                "selected_by_user": True,
                "selection_reference": f"selection-{index}",
                "dossier": _write_dossier(root, index + 1),
                "dry_preview": {
                    "passed": True,
                    "outcome": "ready_to_submit",
                    "final_submit_clicked": False,
                },
            }
            for index in range(count)
        ],
    }


def _day(report, day):
    return next(item for item in report["checkpoints"] if item["day"] == day)


def test_current_evidence_blocks_day_22_and_reports_every_failed_gate():
    report = build_day_12_22_report(_lever(), _greenhouse())
    assert report["summary"]["complete_days"] == []
    assert report["summary"]["blocked_days"] == list(range(12, 23))
    day22 = report["checkpoints"][-1]
    assert day22["passed"] is False
    assert day22["facts"]["exact_backlog"] == [
        "ten_supervised_confirmed_submissions",
        "all_success_evidence_independently_reviewed",
        "explicit_release_approval_reference",
        "human_reviewed_submit_ready",
    ]


def test_day_13_requires_every_challenge_to_remain_needs_review():
    gates = dict(LEVER_PHASE_A)
    gates["all_manual_challenges_remain_needs_review"] = False
    report = build_day_12_22_report(
        _lever(
            25,
            25,
            gates=gates,
            manual_challenge_encounter_count=2,
            manual_challenge_boundary_count=1,
            manual_challenge_violation_count=1,
        ),
        _greenhouse(),
    )
    day13 = _day(report, 13)
    assert day13["passed"] is False
    assert day13["facts"]["manual_challenge_violations"] == 1
    assert "needs_review" in day13["blockers"][-1]


def test_day_15_uses_retained_launch_evidence_not_readiness_only(tmp_path):
    gates = dict(LEVER_PHASE_A)
    readiness = _lever(
        30,
        30,
        gates=gates,
        selected_application_count=99,
        approval_dossier_count=99,
        dry_preview_count=99,
    )
    blocked = build_day_12_22_report(readiness, _greenhouse())
    assert _day(blocked, 15)["passed"] is False

    complete = build_day_12_22_report(
        readiness,
        _greenhouse(),
        _launch(tmp_path),
        lever_phase_b_artifact_root=tmp_path,
    )
    day15 = _day(complete, 15)
    assert day15["passed"] is True
    assert day15["facts"]["ready_application_count"] == 2
    assert day15["facts"]["invalid_dossier_count"] == 0


def test_day_15_rejects_fabricated_64_character_dossier_hashes(tmp_path):
    launch = _launch(tmp_path)
    for index, record in enumerate(launch["applications"]):
        record["dossier"]["dossier_sha256"] = f"{index + 7:064x}"

    report = build_day_12_22_report(
        _lever(30, 30, gates=dict(LEVER_PHASE_A)),
        _greenhouse(),
        launch,
        lever_phase_b_artifact_root=tmp_path,
    )
    day15 = _day(report, 15)
    assert day15["passed"] is False
    assert day15["facts"]["ready_application_count"] == 0
    assert day15["facts"]["invalid_dossier_count"] == 2
    assert {
        item["reason"] for item in day15["facts"]["dossier_validation_errors"]
    } == {"manifest_dossier_sha256_mismatch"}


def test_day_15_rejects_tampered_dossier_artifact_bytes(tmp_path):
    launch = _launch(tmp_path)
    path = tmp_path / launch["applications"][0]["dossier"]["artifact_path"]
    path.write_bytes(path.read_bytes() + b"\n")

    report = build_day_12_22_report(
        _lever(30, 30, gates=dict(LEVER_PHASE_A)),
        _greenhouse(),
        launch,
        lever_phase_b_artifact_root=tmp_path,
    )
    day15 = _day(report, 15)
    assert day15["passed"] is False
    assert day15["facts"]["invalid_dossier_count"] == 1
    assert day15["facts"]["dossier_validation_errors"][0]["reason"] == (
        "artifact_sha256_mismatch"
    )


def test_day_15_rejects_dossier_bound_to_another_application(tmp_path):
    launch = _launch(tmp_path)
    launch["applications"][0]["application_id"] = "999"

    report = build_day_12_22_report(
        _lever(30, 30, gates=dict(LEVER_PHASE_A)),
        _greenhouse(),
        launch,
        lever_phase_b_artifact_root=tmp_path,
    )
    day15 = _day(report, 15)
    assert day15["passed"] is False
    assert day15["facts"]["invalid_dossier_count"] == 1
    assert day15["facts"]["dossier_validation_errors"][0]["reason"] == (
        "artifact_application_id_mismatch"
    )


def test_day_15_does_not_splice_evidence_across_duplicate_records(tmp_path):
    launch = _launch(tmp_path, count=1)
    duplicate = json.loads(json.dumps(launch["applications"][0]))
    launch["applications"][0]["dossier"] = {}
    duplicate["selected_by_user"] = False
    launch["applications"].append(duplicate)

    report = build_day_12_22_report(
        _lever(30, 30, gates=dict(LEVER_PHASE_A)),
        _greenhouse(),
        launch,
        lever_phase_b_artifact_root=tmp_path,
    )
    day15 = _day(report, 15)
    assert day15["passed"] is False
    assert day15["facts"]["ready_application_count"] == 0
    assert day15["facts"]["duplicate_application_count"] == 1


def test_day_22_backlog_includes_false_duplicate_and_uncertain_protections():
    gates = dict(GREENHOUSE_GATES)
    gates["zero_false_submitted_records"] = False
    gates["zero_duplicate_submissions"] = False
    gates["all_uncertain_outcomes_remain_uncertain"] = False
    report = build_day_12_22_report(
        _lever(), _greenhouse(gates=gates, ready=False)
    )
    backlog = report["checkpoints"][-1]["facts"]["exact_backlog"]
    assert "zero_false_submitted_records" in backlog
    assert "zero_duplicate_submissions" in backlog
    assert "all_uncertain_outcomes_remain_uncertain" in backlog


def test_all_checkpoints_can_complete_only_from_all_required_inputs(tmp_path):
    lever_gates = {
        **LEVER_PHASE_A,
        **LEVER_PHASE_B,
        "explicit_separate_promotion_approval": True,
    }
    lever = _lever(
        30,
        30,
        10,
        lever_gates,
        promotion_ready=True,
        manual_challenge_encounter_count=2,
        manual_challenge_boundary_count=2,
    )
    report = build_day_12_22_report(
        lever,
        _greenhouse(GREENHOUSE_GATES, ready=True),
        _launch(tmp_path),
        lever_phase_b_artifact_root=tmp_path,
    )
    assert report["summary"]["complete_days"] == list(range(12, 23))
    assert report["summary"]["blocked_days"] == []
