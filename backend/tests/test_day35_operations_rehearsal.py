from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from app.services.day35_operations_rehearsal import (
    PILOT_CONFIGURATION_PATH,
    REQUIRED_SIMULATION_STAGES,
    audit_explainability_report,
    build_day35_rehearsal_gate,
    run_no_submit_simulation,
    scan_audit_secret_leakage,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _configuration() -> dict:
    return json.loads((REPO_ROOT / PILOT_CONFIGURATION_PATH).read_text(encoding="utf-8"))


def test_rehearsal_runs_full_no_submit_stage_sequence():
    report = run_no_submit_simulation(configuration=_configuration())

    assert report["passed"] is True
    assert report["mode"] == "no_submit_simulation"
    assert set(REQUIRED_SIMULATION_STAGES).issubset(
        {entry["stage"] for entry in report["audit_log"]}
    )
    assert report["missing_stages"] == []
    assert report["safety"] == {
        "network_contacted": False,
        "browser_launched": False,
        "celery_dispatched": False,
        "final_submit_clicked": False,
        "submission_authorized": False,
        "outreach_authorized": False,
    }


def test_quiet_hours_and_platform_cap_are_held_without_babysitting():
    report = run_no_submit_simulation(configuration=_configuration())
    states = {item["candidate_id"]: item["state"] for item in report["timeline"]}

    assert states["candidate-2"] == "held_quiet_hours"
    assert states["candidate-4"] == "held_cap"
    assert report["assertions"]["quiet_hours_verified"] is True
    assert report["assertions"]["platform_cap_exhaustion_verified"] is True
    assert report["assertions"]["no_manual_babysitting_required"] is True


def test_bounded_retry_alert_and_dead_letter_paths_are_exercised():
    report = run_no_submit_simulation(configuration=_configuration())
    timeline = {item["candidate_id"]: item for item in report["timeline"]}
    alert_codes = {item["code"] for item in report["alerts"]}

    assert timeline["candidate-3"]["automatic_retry_count"] == 1
    assert report["assertions"]["bounded_retry_verified"] is True
    assert alert_codes >= {"simulated_source_interruption", "dead_letter_opened"}
    assert report["dead_letters"]
    assert all(item["automatic_retry_allowed"] is False for item in report["dead_letters"])
    assert all(item["submission_authorized"] is False for item in report["dead_letters"])


def test_evidence_shape_never_claims_a_submission():
    report = run_no_submit_simulation(configuration=_configuration())

    assert report["evidence_packets"]
    for packet in report["evidence_packets"]:
        assert packet["evidence_kind"] == "simulation_completion_shape"
        assert packet["final_submit_clicked"] is False
        assert packet["submission_status"] == "not_submitted"
        assert len(packet["payload_sha256"]) == 64
    assert report["assertions"]["no_false_submission_state"] is True
    assert report["assertions"]["no_final_submit_click"] is True


def test_audit_review_requires_explanation_and_false_consequential_authority():
    report = run_no_submit_simulation(configuration=_configuration())
    review = audit_explainability_report(report["audit_log"])

    assert review["all_entries_explainable"] is True
    assert review["no_consequential_authority"] is True
    assert review["secret_leakage_clear"] is True
    assert review["entry_count"] == len(report["audit_log"])


def test_audit_secret_scanner_detects_credentials_without_echoing_them():
    value = {
        "message": "broker failed redis://worker:supersecret@example.invalid:6379/1",
        "authorization": "Bearer abcdefghijklmnopqrstuvwxyz.123456",
    }
    findings = scan_audit_secret_leakage(value)

    assert len(findings) >= 2
    serialized = json.dumps(findings)
    assert "supersecret" not in serialized
    assert "abcdefghijklmnopqrstuvwxyz" not in serialized


def test_incomplete_audit_entry_fails_explainability():
    review = audit_explainability_report(
        [
            {
                "timestamp": "2026-09-01T00:00:00+00:00",
                "stage": "policy_admission",
                "decision": "held",
                "reason_code": "quiet_hours",
                "candidate_id": "candidate-1",
                "submission_authorized": False,
            }
        ]
    )
    assert review["all_entries_explainable"] is False
    assert review["incomplete_entry_indexes"] == [0]


def test_frozen_configuration_is_strictly_no_submit_and_no_promotion():
    config = _configuration()

    assert config["candidate"] == {
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "required_current_maturity": "dry_run",
        "target_maturity": "certified_autonomous",
        "promotion_authorized": False,
    }
    assert config["simulation"]["mode"] == "no_submit"
    assert config["simulation"]["final_submit_allowed"] is False
    assert config["runtime_invariants"]["canonical_autopilot_default_must_remain_false"] is True
    assert config["runtime_invariants"]["real_application_submit_must_remain_false"] is True
    assert config["freeze_policy"]["day39_remains_blocked_until_day38_evidence_and_separate_promotion"] is True


def test_gate_binds_candidate_code_fixture_evidence_recovery_and_policy_digests(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("ALLOW_REAL_APPLICATION_SUBMIT", "false")
    monkeypatch.setenv("ALLOW_REAL_FOLLOWUP_SEND", "false")
    gate = build_day35_rehearsal_gate(
        verification_commit="a" * 40,
        root=REPO_ROOT,
    )
    recommendation = gate["provisional_autonomy_recommendation"]
    bindings = recommendation["source_bindings"]

    assert gate["gate_passed"] is True
    assert recommendation["candidate"] == "lever"
    assert recommendation["eligible_to_enter_shadow_runs"] is True
    assert recommendation["certified_autonomous_recommended"] is False
    assert recommendation["promotion_authorized"] is False
    assert recommendation["live_submission_authorized"] is False
    assert recommendation["day39_promotion_blocked"] is True
    for key in (
        "adapter_name",
        "adapter_version",
        "release_commit",
        "adapter_source_digest",
        "fixture_digest",
        "retained_evidence_digest",
        "manifest_live_evidence_digest",
        "pilot_configuration_digest",
        "phase4_gate_digest",
        "day27_contract_digest",
        "day33_recovery_digest",
        "day35_rehearsal_digest",
    ):
        assert bindings[key]


def test_gate_rejects_drift_in_each_frozen_safety_section(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("ALLOW_REAL_APPLICATION_SUBMIT", "false")
    monkeypatch.setenv("ALLOW_REAL_FOLLOWUP_SEND", "false")

    from app.services import day35_operations_rehearsal as rehearsal

    mutations = (
        ("simulation", "final_submit_allowed", True),
        ("simulation", "recruiter_outreach_allowed", True),
        ("policy", "maximum_automatic_retries_per_attempt", 2),
        ("runtime_invariants", "no_submit_route_in_rehearsal", False),
        ("freeze_policy", "configuration_digest_drift_requires_regate", False),
    )
    original = _configuration()
    for section, setting, unsafe_value in mutations:
        changed = deepcopy(original)
        changed[section][setting] = unsafe_value
        monkeypatch.setattr(rehearsal, "_load_configuration", lambda _root, value=changed: value)

        gate = rehearsal.build_day35_rehearsal_gate(
            verification_commit="e" * 40,
            root=REPO_ROOT,
        )

        assert gate["pilot_configuration_freeze"]["valid"] is False
        assert gate["gate_passed"] is False
        assert gate["provisional_autonomy_recommendation"]["eligible_to_enter_shadow_runs"] is False


def test_exported_gate_digest_covers_executed_evidence(monkeypatch):
    from scripts import build_day35_operations_rehearsal_gate as builder

    payload = {
        "gate_passed": True,
        "gate_sha256": "stale-service-digest",
        "pilot_configuration_freeze": {"valid": True},
        "provisional_autonomy_recommendation": {
            "eligible_to_enter_shadow_runs": True,
            "certified_autonomous_recommended": False,
            "promotion_authorized": False,
            "live_submission_authorized": False,
            "day39_promotion_blocked": True,
        },
    }
    dead_letter = {
        "passed": True,
        "safety": {
            "final_submit_clicked": False,
            "network_contacted": False,
            "submission_authorized": False,
            "outreach_authorized": False,
        },
    }
    monkeypatch.setattr(builder, "build_day35_rehearsal_gate", lambda **_kwargs: deepcopy(payload))
    monkeypatch.setattr(builder, "run_dead_letter_recovery_drill", lambda: dead_letter)
    monkeypatch.setattr(builder, "SOURCES", ())

    gate = builder.build_gate("f" * 40)
    digest = gate.pop("gate_sha256")

    assert digest == builder.canonical_sha256(gate)


def test_provisional_recommendation_retains_future_shadow_and_supervised_blockers(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("ALLOW_REAL_APPLICATION_SUBMIT", "false")
    monkeypatch.setenv("ALLOW_REAL_FOLLOWUP_SEND", "false")
    gate = build_day35_rehearsal_gate(
        verification_commit="b" * 40,
        root=REPO_ROOT,
    )
    blockers = set(
        gate["provisional_autonomy_recommendation"]["remaining_autonomy_contract_blockers"]
    )

    assert "ten_distinct_supervised_confirmed_submissions_missing" in blockers
    assert "signed_exact_commit_autonomy_release_manifest_missing" in blockers
    assert any(item.startswith("shadow:four_hour_unattended_passed") for item in blockers)
    assert any(item.startswith("shadow:eight_hour_unattended_passed") for item in blockers)
    assert any(item.startswith("shadow:twenty_four_hour_unattended_passed") for item in blockers)


def test_completed_day33_recovery_evidence_is_rechecked_in_gate(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "false")
    monkeypatch.setenv("ALLOW_REAL_APPLICATION_SUBMIT", "false")
    monkeypatch.setenv("ALLOW_REAL_FOLLOWUP_SEND", "false")
    gate = build_day35_rehearsal_gate(
        verification_commit="c" * 40,
        root=REPO_ROOT,
    )
    recovery = gate["completed_recovery_evidence"]

    assert recovery["passed"] is True
    assert set(recovery["failure_modes"]) >= {
        "process_crash",
        "worker_restart",
        "redis_interruption",
        "database_lock",
        "browser_death",
        "device_reboot",
    }
    assert recovery["assertions"]["no_duplicate_submission"] is True
    assert recovery["assertions"]["no_status_corruption"] is True
    assert recovery["digest"].startswith("sha256:")


def test_gate_fails_if_runtime_autopilot_is_enabled(monkeypatch):
    monkeypatch.setenv("AUTOPILOT_ENABLED", "true")
    monkeypatch.setenv("ALLOW_REAL_APPLICATION_SUBMIT", "false")
    monkeypatch.setenv("ALLOW_REAL_FOLLOWUP_SEND", "false")

    # Clear cached settings factories before and after this mutation.
    from app.config import get_settings
    from app.services.operations_settings import get_operations_settings

    get_settings.cache_clear()
    get_operations_settings.cache_clear()
    try:
        gate = build_day35_rehearsal_gate(
            verification_commit="d" * 40,
            root=REPO_ROOT,
        )
        assert gate["gate_passed"] is False
        assert gate["runtime_safety"]["autopilot_enabled"] is True
        assert gate["provisional_autonomy_recommendation"]["eligible_to_enter_shadow_runs"] is False
    finally:
        get_settings.cache_clear()
        get_operations_settings.cache_clear()
