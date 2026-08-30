import re
import subprocess

import pytest

from app.services import phase4_candidate_gate
from app.services.phase4_candidate_gate import (
    ADAPTER_INTEGRATION_PATHS,
    COMMON_SOURCE_PATHS,
    SOURCE_PATHS,
    _candidate_eligible,
    _lever_metrics,
    build_phase4_candidate_gate,
)


SHA = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()


def _gate():
    return build_phase4_candidate_gate(verification_commit=SHA)


def test__temporary_phase4_lever_digest_probe():
    gate = _gate()
    lever = next(row for row in gate["adapter_freeze"] if row["adapter"] == "lever")
    raise AssertionError(
        "PHASE4_LEVER_FINAL_DIGEST_PROBE "
        f"source={lever['digests']['adapter_source_sha256']} "
        f"fixture={lever['digests']['fixture_regression_sha256']}"
    )


def test_phase4_gate_selects_lever_from_retained_evidence_without_promotion():
    gate = _gate()

    assert gate["gate_passed"] is True
    assert gate["drift"] == []
    assert gate["candidate"]["adapter"] == "lever"
    assert gate["candidate"]["selection_scope"] == "unattended_pilot_preparation_only"
    assert gate["candidate"]["promotion_authorized"] is False
    assert gate["candidate"]["unattended_submission_allowed"] is False
    assert gate["candidate"]["certified_autonomous"] is False
    assert gate["candidate"]["metrics"]["supervised_confirmed_count"] == 0


def test_phase4_ranking_is_evidence_ordered_not_preference_ordered():
    gate = _gate()
    ranking = gate["ranking"]

    assert [row["adapter"] for row in ranking] == ["lever", "greenhouse", "ashby"]
    assert ranking[0]["ranking_key"] == [0, 30, 30, 2, 1, 1]
    assert ranking[1]["ranking_key"] == [0, 30, 30, 0, 0, 0]
    assert ranking[2]["ranking_key"][0] == 0
    assert ranking[2]["ranking_key"][1] == 1


def test_phase4_freezes_all_adapter_versions_and_retains_digests():
    gate = _gate()
    frozen = {row["adapter"]: row for row in gate["adapter_freeze"]}

    assert {name: row["version"] for name, row in frozen.items()} == {
        "greenhouse": "1.1.1",
        "lever": "1.1.0",
        "ashby": "1.1.0",
        "smartrecruiters": "1.1.0",
        "workday": "1.1.0",
    }
    assert {name: row["maturity"] for name, row in frozen.items()} == {
        "greenhouse": "dry_run",
        "lever": "dry_run",
        "ashby": "dry_run",
        "smartrecruiters": "detect_only",
        "workday": "detect_only",
    }
    for row in frozen.values():
        assert re.fullmatch(r"[0-9a-f]{64}", row["digests"]["adapter_source_sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", row["digests"]["fixture_regression_sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", row["digests"]["manifest_live_evidence_sha256"])
    for name in ("greenhouse", "lever", "ashby"):
        assert re.fullmatch(r"[0-9a-f]{64}", frozen[name]["digests"]["retained_evidence_sha256"])


def test_phase4_source_digest_includes_installed_adapter_integrations():
    assert COMMON_SOURCE_PATHS == (
        "backend/app/services/ats_base.py",
        "backend/app/services/ats_registry.py",
        "backend/app/services/control_engine.py",
    )
    for source_paths in SOURCE_PATHS.values():
        assert set(COMMON_SOURCE_PATHS).issubset(source_paths)

    assert ADAPTER_INTEGRATION_PATHS == {
        "ashby": (
            "backend/app/services/ashby_profile_aliases.py",
            "backend/app/services/form_filler_v2.py",
        ),
        "smartrecruiters": (
            "backend/app/services/smartrecruiters_challenge.py",
            "backend/app/services/smartrecruiters_contract.py",
        ),
        "workday": (
            "backend/app/services/workday_challenge.py",
            "backend/app/services/workday_popup_boundaries.py",
            "backend/app/services/workday_port_integration.py",
        ),
    }
    for adapter, integration_paths in ADAPTER_INTEGRATION_PATHS.items():
        assert set(integration_paths).issubset(SOURCE_PATHS[adapter])


def test_phase4_digest_drift_fails_the_gate(monkeypatch):
    monkeypatch.setattr(phase4_candidate_gate, "_digest_paths", lambda *_: "0" * 64)

    gate = _gate()

    assert gate["gate_passed"] is False
    assert "lever:adapter_source_sha256_drift" in gate["drift"]
    assert "lever:fixture_regression_sha256_drift" in gate["drift"]


def test_phase4_publishes_remaining_supervised_and_shadow_boundaries():
    gate = _gate()
    blockers = set(gate["candidate"]["remaining_blockers"])
    thresholds = gate["autonomy_contract_thresholds"]

    assert "ten_distinct_supervised_confirmed_submissions_missing" in blockers
    assert "independent_success_review_missing" in blockers
    assert "separate_explicit_promotion_approval_missing" in blockers
    assert "signed_exact_commit_autonomy_release_manifest_missing" in blockers
    assert thresholds["minimum_supervised_attempts"] == 10
    assert thresholds["minimum_success_rate"] == 0.98
    assert any(item.startswith("shadow:four_hour_unattended_passed") for item in blockers)
    assert any(item.startswith("shadow:eight_hour_unattended_passed") for item in blockers)
    assert any(item.startswith("shadow:twenty_four_hour_unattended_passed") for item in blockers)


def test_phase4_runtime_remains_non_autonomous():
    gate = _gate()

    assert gate["runtime_safety"] == {
        "real_submission_enabled": False,
        "autopilot_enabled": False,
        "autonomous_adapters": [],
        "safe": True,
    }


def test_phase4_requires_exact_verification_commit():
    with pytest.raises(ValueError, match="40-character"):
        build_phase4_candidate_gate(verification_commit="short")


def test_phase4_rejects_commit_that_does_not_match_checkout():
    with pytest.raises(ValueError, match="clean checkout of verification_commit"):
        build_phase4_candidate_gate(verification_commit="1" * 40)


@pytest.mark.parametrize(
    ("counter", "invalid_value"),
    [
        ("false_submitted_count", None),
        ("duplicate_submission_count", -1),
        ("uncertain_status_violation_count", "0"),
    ],
)
def test_lever_missing_or_invalid_safety_counter_fails_closed(counter, invalid_value):
    summary = {
        "false_submitted_count": 0,
        "duplicate_submission_count": 0,
        "uncertain_status_violation_count": 0,
    }
    if invalid_value is None:
        summary.pop(counter)
    else:
        summary[counter] = invalid_value

    metrics = _lever_metrics({"summary": summary})

    assert _candidate_eligible("dry_run", metrics) is False
