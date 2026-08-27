from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app.services.day40_second_wave import (
    DAY40_MAX_ATTEMPTS,
    build_day40_second_wave_certification,
    build_day40_second_wave_readiness,
    expected_day40_acknowledgment,
)


REVISION = "a" * 40
REPORT_SHA = "b" * 64
NOW = datetime(2026, 9, 6, 14, 0, tzinfo=timezone.utc)


def _inputs():
    first_wave = {
        "status": "completed",
        "release_candidate_revision": REVISION,
        "report_sha256": REPORT_SHA,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "attempted_count": 2,
        "accounted_attempt_count": 2,
        "critical_defect_count": 0,
        "duplicate_submission_count": 0,
        "false_submitted_status_count": 0,
        "wrong_target_count": 0,
        "guessed_required_answer_count": 0,
        "ambiguous_confirmation_count": 0,
        "breaker_trip_count": 0,
        "policy_escape_count": 0,
        "unresolved_outcome_count": 0,
        "confirmation_evidence_reconciled": True,
        "reserved_attempts_non_reclaiming": True,
    }
    adapter = {
        "name": "lever",
        "version": "1.1.0",
        "maturity": "certified_autonomous",
        "autonomous_submission_allowed": True,
    }
    runtime = {
        "current_revision": REVISION,
        "allow_real_application_submit": False,
        "allow_real_followup_send": False,
        "global_kill_switch": False,
        "live_window_authorized": False,
    }
    policy = {
        "ready": True,
        "policy_profile": "production",
        "circuit_breaker_clear": True,
        "quiet_hours_active": False,
        "remaining_daily": 5,
        "remaining_weekly": 20,
    }
    operations = {
        "queue_prioritization_ready": True,
        "cap_enforcement_ready": True,
        "followup_scheduler_ready": True,
        "confirmation_reconciliation_ready": True,
    }
    owner = {
        "approved": True,
        "approval_reference": "day40-wave-2",
        "approved_for_commit": REVISION,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "max_submission_attempts": 2,
        "starts_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=6)).isoformat(),
        "acknowledgment": expected_day40_acknowledgment(
            revision=REVISION,
            attempt_cap=2,
        ),
    }
    return first_wave, adapter, runtime, policy, operations, owner


def _readiness(**overrides):
    first_wave, adapter, runtime, policy, operations, owner = _inputs()
    values = {
        "first_wave_report": first_wave,
        "adapter_state": adapter,
        "runtime_safety": runtime,
        "policy_state": policy,
        "operations_state": operations,
        "owner_request": owner,
        "now": NOW,
    }
    values.update(overrides)
    return build_day40_second_wave_readiness(**values)


def _successful_wave():
    return {
        "status": "completed",
        "release_candidate_revision": REVISION,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "authorized_attempt_cap": 2,
        "attempted_count": 2,
        "accounted_attempt_count": 2,
        "critical_defect_count": 0,
        "duplicate_submission_count": 0,
        "false_submitted_status_count": 0,
        "wrong_target_count": 0,
        "guessed_required_answer_count": 0,
        "ambiguous_confirmation_count": 0,
        "breaker_trip_count": 0,
        "policy_escape_count": 0,
        "unresolved_outcome_count": 0,
        "queue_prioritization_exercised": True,
        "cap_enforcement_exercised": True,
        "followup_scheduling_exercised": True,
        "confirmation_evidence_reconciled": True,
        "platform_external_evidence_compared": True,
        "external_confirmation_unavailable_documented": False,
        "reserved_attempts_non_reclaiming": True,
        "live_window_closed": True,
        "real_submission_disabled_after_wave": True,
        "real_followup_send_disabled": True,
    }


def test_day40_second_wave_readiness_passes_only_as_non_authoritative_tooling():
    result = _readiness()

    assert result["second_wave_authorization_eligible"] is True
    assert result["authorization_persisted"] is False
    assert result["live_window_authorized"] is False
    assert result["real_submission_enabled"] is False
    assert result["real_followup_send_enabled"] is False
    assert len(result["report_sha256"]) == 64
    assert result["next_action"] == "persist_separate_day40_authorization"


def test_day40_refuses_first_wave_with_any_critical_defect():
    first_wave, *_ = _inputs()
    first_wave["critical_defect_count"] = 1

    result = _readiness(first_wave_report=first_wave)

    assert result["second_wave_authorization_eligible"] is False
    assert "first_wave.first_wave_zero_critical_defects" in result["blockers"]


def test_day40_refuses_duplicate_or_false_submission_history():
    first_wave, *_ = _inputs()
    first_wave["duplicate_submission_count"] = 1
    first_wave["false_submitted_status_count"] = 1

    result = _readiness(first_wave_report=first_wave)

    assert result["second_wave_authorization_eligible"] is False
    assert "first_wave.first_wave_zero_duplicates" in result["blockers"]
    assert "first_wave.first_wave_zero_false_submitted_status" in result["blockers"]


def test_day40_refuses_unresolved_first_wave_outcome():
    first_wave, *_ = _inputs()
    first_wave["unresolved_outcome_count"] = 1

    result = _readiness(first_wave_report=first_wave)

    assert result["second_wave_authorization_eligible"] is False
    assert "first_wave.first_wave_zero_unresolved_outcomes" in result["blockers"]


def test_day40_requires_exact_same_runtime_revision():
    _, _, runtime, _, _, _ = _inputs()
    runtime["current_revision"] = "c" * 40

    result = _readiness(runtime_safety=runtime)

    assert result["second_wave_authorization_eligible"] is False
    assert "runtime.runtime_revision_matches_first_wave" in result["blockers"]


def test_day40_requires_real_submit_disabled_between_waves():
    _, _, runtime, _, _, _ = _inputs()
    runtime["allow_real_application_submit"] = True

    result = _readiness(runtime_safety=runtime)

    assert result["second_wave_authorization_eligible"] is False
    assert "runtime.real_submission_disabled_between_waves" in result["blockers"]


def test_day40_requires_policy_capacity_for_requested_cap():
    _, _, _, policy, _, _ = _inputs()
    policy["remaining_daily"] = 1

    result = _readiness(policy_state=policy)

    assert result["second_wave_authorization_eligible"] is False
    assert "policy.daily_capacity_covers_second_wave" in result["blockers"]


def test_day40_requires_queue_cap_followup_and_reconciliation_readiness():
    _, _, _, _, operations, _ = _inputs()
    operations["followup_scheduler_ready"] = False

    result = _readiness(operations_state=operations)

    assert result["second_wave_authorization_eligible"] is False
    assert "operations.followup_scheduler_ready" in result["blockers"]


def test_day40_owner_cap_is_never_larger_than_two_attempts():
    _, _, _, _, _, owner = _inputs()
    owner["max_submission_attempts"] = DAY40_MAX_ATTEMPTS + 1
    owner["acknowledgment"] = expected_day40_acknowledgment(
        revision=REVISION,
        attempt_cap=DAY40_MAX_ATTEMPTS + 1,
    )

    result = _readiness(owner_request=owner)

    assert result["second_wave_authorization_eligible"] is False
    assert "owner.attempt_cap_conservative" in result["blockers"]


def test_day40_owner_acknowledgment_is_exact_and_commit_bound():
    _, _, _, _, _, owner = _inputs()
    owner["acknowledgment"] += " EXTRA"

    result = _readiness(owner_request=owner)

    assert result["second_wave_authorization_eligible"] is False
    assert "owner.owner_acknowledgment_exact" in result["blockers"]


def test_day40_certification_passes_clean_second_wave():
    result = build_day40_second_wave_certification(
        second_wave_report=_successful_wave(),
        verification_revision=REVISION,
    )

    assert result["passed"] is True
    assert result["day41_entry_eligible"] is True
    assert result["blockers"] == []
    assert len(result["report_sha256"]) == 64


def test_day40_certification_accepts_documented_external_confirmation_unavailability():
    wave = _successful_wave()
    wave["platform_external_evidence_compared"] = False
    wave["external_confirmation_unavailable_documented"] = True

    result = build_day40_second_wave_certification(
        second_wave_report=wave,
        verification_revision=REVISION,
    )

    assert result["passed"] is True


def test_day40_certification_fails_on_duplicate_even_when_everything_else_is_green():
    wave = _successful_wave()
    wave["duplicate_submission_count"] = 1

    result = build_day40_second_wave_certification(
        second_wave_report=wave,
        verification_revision=REVISION,
    )

    assert result["passed"] is False
    assert result["day41_entry_eligible"] is False
    assert "zero_duplicates" in result["blockers"]


def test_day40_certification_requires_live_window_closed_and_submit_disabled_after_wave():
    wave = _successful_wave()
    wave["live_window_closed"] = False
    wave["real_submission_disabled_after_wave"] = False

    result = build_day40_second_wave_certification(
        second_wave_report=wave,
        verification_revision=REVISION,
    )

    assert result["passed"] is False
    assert "live_window_closed_after_wave" in result["blockers"]
    assert "real_submission_disabled_after_wave" in result["blockers"]


def test_day40_certification_requires_queue_cap_and_followup_exercises():
    wave = _successful_wave()
    wave["queue_prioritization_exercised"] = False
    wave["cap_enforcement_exercised"] = False
    wave["followup_scheduling_exercised"] = False

    result = build_day40_second_wave_certification(
        second_wave_report=wave,
        verification_revision=REVISION,
    )

    assert result["passed"] is False
    assert "queue_prioritization_exercised" in result["blockers"]
    assert "cap_enforcement_exercised" in result["blockers"]
    assert "followup_scheduling_exercised" in result["blockers"]


def test_day40_certification_is_exact_revision_bound():
    result = build_day40_second_wave_certification(
        second_wave_report=_successful_wave(),
        verification_revision="d" * 40,
    )

    assert result["passed"] is False
    assert "second_wave_revision_exact" in result["blockers"]


def test_day40_readiness_report_is_deterministic_for_same_inputs():
    first = _readiness()
    second = _readiness()

    assert first["report_sha256"] == second["report_sha256"]
    assert first == second
