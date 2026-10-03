from datetime import datetime, timedelta, timezone

from app.services.day39_live_window import (
    DAY39_LIVE_MAX_ATTEMPTS,
    build_day39_live_window_readiness,
    expected_live_window_acknowledgment,
)


REVISION = "a" * 40
NOW = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)


def _promotion():
    return {
        "passed": True,
        "promotion_authorized": True,
        "live_window_authorized": False,
        "real_submission_authorized": False,
        "release_candidate_revision": REVISION,
        "target_adapter": "lever",
        "target_adapter_version": "1.1.0",
        "target_maturity": "certified_autonomous",
    }


def _adapter():
    return {
        "name": "lever",
        "version": "1.1.0",
        "maturity": "certified_autonomous",
        "autonomous_submission_allowed": True,
    }


def _runtime():
    return {
        "current_revision": REVISION,
        "allow_real_application_submit": False,
        "allow_real_followup_send": False,
        "global_kill_switch": False,
        "live_window_authorized": False,
    }


def _policy():
    return {
        "ready": True,
        "policy_profile": "production",
        "circuit_breaker_clear": True,
        "quiet_hours_active": False,
        "remaining_daily": 5,
        "remaining_weekly": 20,
    }


def _owner(*, cap: int = 2):
    return {
        "approved": True,
        "approval_reference": "day39-owner-first-wave",
        "approved_for_commit": REVISION,
        "adapter": "lever",
        "adapter_version": "1.1.0",
        "max_submission_attempts": cap,
        "starts_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=6)).isoformat(),
        "acknowledgment": expected_live_window_acknowledgment(
            revision=REVISION,
            attempt_cap=cap,
        ),
    }


def _evaluate(**overrides):
    values = {
        "promotion": _promotion(),
        "adapter_state": _adapter(),
        "runtime_safety": _runtime(),
        "policy_state": _policy(),
        "owner_request": _owner(),
        "now": NOW,
    }
    values.update(overrides)
    return build_day39_live_window_readiness(**values)


def test_exact_promoted_head_and_bounded_owner_request_are_eligible_only_for_persistence():
    report = _evaluate()

    assert report["authorization_eligible"] is True
    assert report["authorization_persisted"] is False
    assert report["live_window_authorized"] is False
    assert report["real_submission_enabled"] is False
    assert report["blockers"] == []
    assert report["requested_attempt_cap"] == 2
    assert report["maximum_attempt_cap"] == DAY39_LIVE_MAX_ATTEMPTS
    assert report["next_action"] == "persist_separate_owner_live_window_authorization"


def test_promotion_alone_cannot_be_reused_as_live_window_authority():
    promotion = _promotion()
    promotion["live_window_authorized"] = True

    report = _evaluate(promotion=promotion)

    assert report["authorization_eligible"] is False
    assert "promotion.promotion_did_not_pre_authorize_live_window" in report["blockers"]


def test_global_submit_flag_must_still_be_false_when_authorization_is_created():
    runtime = _runtime()
    runtime["allow_real_application_submit"] = True

    report = _evaluate(runtime_safety=runtime)

    assert report["authorization_eligible"] is False
    assert "runtime.real_submission_still_disabled_during_authorization" in report["blockers"]
    assert report["invariants"]["global_submit_flag_is_not_authority"] is True


def test_live_window_must_bind_exact_promoted_runtime_commit():
    runtime = _runtime()
    runtime["current_revision"] = "b" * 40

    report = _evaluate(runtime_safety=runtime)

    assert report["authorization_eligible"] is False
    assert "runtime.runtime_revision_exact" in report["blockers"]


def test_owner_request_cannot_target_a_different_commit():
    owner = _owner()
    owner["approved_for_commit"] = "b" * 40

    report = _evaluate(owner_request=owner)

    assert report["authorization_eligible"] is False
    assert "owner.owner_commit_exact" in report["blockers"]


def test_adapter_must_already_be_certified_autonomous_before_live_window():
    adapter = _adapter()
    adapter["maturity"] = "dry_run"
    adapter["autonomous_submission_allowed"] = False

    report = _evaluate(adapter_state=adapter)

    assert report["authorization_eligible"] is False
    assert "adapter.adapter_certified_autonomous" in report["blockers"]
    assert "adapter.adapter_autonomous_submission_capability" in report["blockers"]


def test_first_wave_attempt_cap_is_hard_bounded():
    owner = _owner(cap=DAY39_LIVE_MAX_ATTEMPTS + 1)

    report = _evaluate(owner_request=owner)

    assert report["authorization_eligible"] is False
    assert "owner.attempt_cap_is_conservative" in report["blockers"]


def test_policy_capacity_must_cover_the_entire_requested_attempt_cap():
    policy = _policy()
    policy["remaining_daily"] = 1

    report = _evaluate(policy_state=policy)

    assert report["authorization_eligible"] is False
    assert "policy.daily_capacity_covers_window" in report["blockers"]


def test_window_cannot_start_in_quiet_hours_or_with_breaker_open():
    policy = _policy()
    policy["quiet_hours_active"] = True
    policy["circuit_breaker_clear"] = False

    report = _evaluate(policy_state=policy)

    assert report["authorization_eligible"] is False
    assert "policy.quiet_hours_clear_at_authorization" in report["blockers"]
    assert "policy.circuit_breaker_clear" in report["blockers"]


def test_window_expiry_and_duration_fail_closed():
    expired = _owner()
    expired["starts_at"] = (NOW - timedelta(hours=2)).isoformat()
    expired["expires_at"] = (NOW - timedelta(hours=1)).isoformat()

    expired_report = _evaluate(owner_request=expired)
    assert expired_report["authorization_eligible"] is False
    assert "owner.window_not_expired" in expired_report["blockers"]
    assert "owner.window_start_not_stale" in expired_report["blockers"]

    too_long = _owner()
    too_long["expires_at"] = (NOW + timedelta(hours=13)).isoformat()
    long_report = _evaluate(owner_request=too_long)
    assert long_report["authorization_eligible"] is False
    assert "owner.window_duration_bounded" in long_report["blockers"]


def test_owner_acknowledgment_is_exact_and_commit_bound():
    owner = _owner()
    owner["acknowledgment"] += " please"

    report = _evaluate(owner_request=owner)

    assert report["authorization_eligible"] is False
    assert "owner.owner_acknowledgment_exact" in report["blockers"]


def test_followup_send_and_kill_switch_remain_independent_hard_blocks():
    runtime = _runtime()
    runtime["allow_real_followup_send"] = True
    runtime["global_kill_switch"] = True

    report = _evaluate(runtime_safety=runtime)

    assert report["authorization_eligible"] is False
    assert "runtime.real_followup_send_disabled" in report["blockers"]
    assert "runtime.global_kill_switch_clear" in report["blockers"]


def test_missing_or_malformed_owner_times_fail_closed_without_exception():
    owner = _owner()
    owner["starts_at"] = "not-a-time"
    owner.pop("expires_at")

    report = _evaluate(owner_request=owner)

    assert report["authorization_eligible"] is False
    assert "owner.window_start_valid" in report["blockers"]
    assert "owner.window_expiry_valid" in report["blockers"]
