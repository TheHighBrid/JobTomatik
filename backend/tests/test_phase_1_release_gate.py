import csv
import json
import re
import subprocess
from pathlib import Path

from app.services.ats_manifest import ats_certification_manifest
from app.services.lever_pilot_ledger_boundary import read_lever_pilot_readiness


ROOT = Path(__file__).resolve().parents[2]
PHASE_GATE_PATH = ROOT / "docs/roadmaps/baselines/2026-07-29-day-07-phase-1-gate.json"
FREEZE_PATH = ROOT / "docs/operations/lever-phase-2-measurement-freeze.json"
BACKLOG_PATH = ROOT / "docs/roadmaps/2026-07-29-day-07-backlog-surgery.json"
ROADMAP_PATH = ROOT / "docs/roadmaps/JOBTOMATIK_AUTONOMY_42_DAY_PLAN.md"
BASELINE_PATH = ROOT / "backend/evidence/lever-phase-a-baseline.csv"
READINESS_PATH = ROOT / "backend/evidence/lever-pilot-readiness.json"
SUPERSESSION_PATH = ROOT / "backend/evidence/lever-phase-a-supersessions.json"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _env_example():
    values = {}
    for raw_line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_phase_1_manifest_covers_every_completed_control_day():
    gate = _json(PHASE_GATE_PATH)

    assert gate["campaign_day"] == 7
    assert gate["phase"]["number"] == 1
    assert gate["phase"]["status"] in {
        "pending_exact_head_ci",
        "passed_on_verified_parent_head",
        "passed",
    }
    assert [item["day"] for item in gate["completed_work"]] == [1, 2, 3, 4, 5, 6]
    assert [item.get("pull_request") for item in gate["completed_work"][1:]] == [155, 156, 157, 158, 160]
    assert gate["corrective_hardening"]["pull_request"] == 159

    controls = gate["verified_controls"]
    assert controls
    assert all(controls.values())
    assert gate["expected_release_results"] == {
        "false_submitted_records": 0,
        "duplicate_terminal_submissions": 0,
        "unsafe_handoff_resumes": 0,
        "adapter_promotions": 0,
        "live_submissions": 0,
    }


def test_phase_1_keeps_all_execution_and_submission_defaults_disabled():
    gate = _json(PHASE_GATE_PATH)
    example = _env_example()

    for key in (
        "AUTOPILOT_ENABLED",
        "ALLOW_REAL_APPLICATION_SUBMIT",
        "GREENHOUSE_SUPERVISED_PILOT_ENABLED",
        "LEVER_SUPERVISED_PILOT_ENABLED",
        "ENABLE_RESUMABLE_HANDOFFS",
    ):
        assert gate["safety_defaults"][key] is False
        assert example[key].lower() == "false"

    assert gate["safety_defaults"]["AUTOMATION_GLOBAL_KILL_SWITCH"] is False
    assert example["AUTOMATION_GLOBAL_KILL_SWITCH"].lower() == "false"


def test_canonical_adapter_manifest_has_no_autonomous_adapter():
    gate = _json(PHASE_GATE_PATH)
    manifest = ats_certification_manifest()
    maturities = {item["name"]: item["maturity"] for item in manifest["adapters"]}

    assert maturities == gate["adapter_maturity"]
    assert manifest["autonomous_adapters"] == []
    assert gate["autonomous_adapters"] == []


def test_lever_phase_2_freeze_keeps_launch_snapshot_separate_from_current_progress(tmp_path):
    freeze = _json(FREEZE_PATH)
    supersession = _json(SUPERSESSION_PATH)
    calculated = read_lever_pilot_readiness(
        baseline_path=BASELINE_PATH,
        ledger_path=tmp_path / "missing-phase-b-ledger.jsonl",
    )
    current = calculated["summary"]["qualifying_dry_run_count"]

    assert freeze["starting_point"]["qualifying_dry_runs"] == 0
    assert freeze["starting_point"]["manual_challenge_boundary_rows"] == 2
    assert 0 <= current <= freeze["starting_point"]["required_qualifying_dry_runs"]
    assert calculated["summary"]["manual_challenge_boundary_count"] == 1
    assert supersession["target"] == {
        "region": "eu",
        "site": "lever",
        "posting_id": "065f4538-7347-4207-909f-4ea68f63b4af",
    }
    assert supersession["superseded"]["run_id"] == "github-actions-30337038142-1"
    assert supersession["superseding"]["artifact_path"] == (
        "lever-phase-a-artifacts/D8-043/lever-phase-a-report.json"
    )
    assert supersession["safety"] == {
        "final_submit_clicked": False,
        "historical_boundary_preserved": True,
        "quota_credit_counted_once": True,
    }
    assert calculated["summary"]["promotion_ready"] is False
    assert freeze["promotion"]["authorized"] is False
    assert freeze["promotion"]["real_submission_allowed"] is False


def test_frozen_lever_inputs_remain_reproducible_historical_git_blobs():
    freeze = _json(FREEZE_PATH)
    locked = freeze["locked_input_blobs"]

    assert set(locked) == set(freeze["canonical_inputs"])
    assert all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in locked.values())

    for relative_path, expected_sha in locked.items():
        source = ROOT / relative_path
        assert source.is_file(), relative_path
        object_type = subprocess.check_output(
            ["git", "cat-file", "-t", expected_sha],
            cwd=ROOT,
            text=True,
        ).strip()
        assert object_type == "blob", relative_path
        historical_bytes = subprocess.check_output(
            ["git", "cat-file", "blob", expected_sha],
            cwd=ROOT,
        )
        reproduced_sha = subprocess.check_output(
            ["git", "hash-object", "--stdin"],
            cwd=ROOT,
            input=historical_bytes,
        ).decode("utf-8").strip()
        assert reproduced_sha == expected_sha, relative_path


def test_phase_2_daily_targets_restart_from_zero_without_phantom_credit():
    freeze = _json(FREEZE_PATH)

    assert freeze["daily_targets"] == {
        "day_8": "lock_at_least_30_viable_distinct_sites_from_at_least_40_reviewed_active_postings",
        "day_9": 5,
        "day_10": 10,
        "day_11": 15,
        "day_12": 20,
        "day_13": 25,
        "day_14": 30,
    }
    assert "two retained CAPTCHA-boundary rows do not qualify" in freeze["retroactive_credit_policy"]


def test_backlog_surgery_retains_roadmaps_and_splits_exact_phase_2_queue():
    surgery = _json(BACKLOG_PATH)
    retained = {
        item["number"]
        for item in surgery["decisions"]
        if item["type"] == "retain_issue"
    }
    split = next(item for item in surgery["decisions"] if item["type"] == "split_execution_queue")

    assert retained == {13, 86, 154}
    assert split["number"] == 161
    assert split["parent_issue"] == 86
    assert surgery["issues_closed_today"] == []
    assert surgery["phase_2_active_queue"]["starting_qualifying_count"] == 0
    assert surgery["phase_2_active_queue"]["required_qualifying_count"] == 30


def test_roadmap_uses_the_frozen_zero_of_thirty_starting_line():
    roadmap = ROADMAP_PATH.read_text(encoding="utf-8")

    assert "# Phase 2: Complete Lever Phase A, 0/30 to 30/30" in roadmap
    assert "Lever Phase A: 0 qualifying retained dry runs out of 30" in roadmap
    assert "draft PR #152" not in roadmap
    assert "## Day 9, Thursday August 6: Lever dry runs 1 through 5" in roadmap
    assert "**Daily target:** readiness 5/30 or higher" in roadmap
    assert "- [ ] Update issue #161 with final truthful Phase A evidence." in roadmap


def test_phase_1_workflow_covers_measurement_and_clean_release_contracts():
    workflow = (ROOT / ".github/workflows/phase-1-release-gate.yml").read_text(encoding="utf-8")

    assert "tests/test_phase_1_release_gate.py" in workflow
    assert "scripts/certify_lever_pilot_readiness.py" in workflow
    assert "bash scripts/verify.sh fast" in workflow
    assert "bash scripts/verify.sh safety" in workflow
    assert "qualifying_dry_run_count'] == 0" not in workflow
    assert ".github/workflows/lever-phase-a-certification.yml" in workflow
    assert "tests/test_day06_operational_safety.py" in workflow
    assert "PYTHONPATH: ." in workflow
    assert "AUTOPILOT_ENABLED: \"false\"" in workflow
    assert "ALLOW_REAL_APPLICATION_SUBMIT: \"false\"" in workflow
    assert "ENABLE_RESUMABLE_HANDOFFS: \"false\"" in workflow
    assert "fetch-depth: 0" in workflow
