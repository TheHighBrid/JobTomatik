from __future__ import annotations

from types import SimpleNamespace

from app.services.day38_runtime import (
    DAY38_POLICY_SNAPSHOT_KEY,
    DAY38_POLICY_TELEMETRY_VERSION,
)
from app.services.day38_shadow_endurance import _policy_transition_report


def _diagnostic(
    *,
    active: bool,
    count: int,
    observed_at: str,
    members: list[int],
    cap: int = 5,
) -> dict:
    return {
        "version": DAY38_POLICY_TELEMETRY_VERSION,
        "observed_at": observed_at,
        "authoritative": False,
        "quiet_hours": {
            "start_hour_utc": 0,
            "end_hour_utc": 6,
            "configured": True,
            "active": active,
        },
        "rolling_24h_capacity": {
            "count": count,
            "cap": cap,
            "remaining": max(0, cap - count),
            "at_or_above_cap": count >= cap,
            "member_application_ids": members,
            "semantics": "rolling_previous_24_hours",
        },
        "production_decision": {
            "allowed": not active and count < cap,
            "code": "quiet_hours" if active else (
                "application_cap_reached" if count >= cap else "autopilot_allowed"
            ),
        },
        "safety": {
            "used_to_authorize_shadow_execution": False,
            "used_to_block_shadow_execution": False,
            "submission_authorized": False,
            "outreach_authorized": False,
        },
    }


def _cycle(number: int, diagnostic: dict) -> SimpleNamespace:
    return SimpleNamespace(
        cycle_number=number,
        status="completed",
        scheduler_result={
            "policy_profile": "shadow_test",
            "production_limits_enforced": False,
        },
        reconciliation_snapshot={DAY38_POLICY_SNAPSHOT_KEY: diagnostic},
    )


def test_day38_policy_report_requires_real_quiet_and_rolling_window_transitions():
    report = _policy_transition_report(
        [
            _cycle(
                1,
                _diagnostic(
                    active=False,
                    count=7,
                    observed_at="2026-09-04T12:00:00+00:00",
                    members=[1, 2, 3, 4, 5, 6, 7],
                ),
            ),
            _cycle(
                2,
                _diagnostic(
                    active=True,
                    count=8,
                    observed_at="2026-09-05T01:00:00+00:00",
                    members=[2, 3, 4, 5, 6, 7, 8, 9],
                ),
            ),
            _cycle(
                3,
                _diagnostic(
                    active=False,
                    count=9,
                    observed_at="2026-09-05T11:30:00+00:00",
                    members=[4, 5, 6, 7, 8, 9, 10, 11, 12],
                ),
            ),
        ]
    )

    assert report["passed"] is True
    assert report["checks"]["quiet_hours_transition_observed"] is True
    assert report["checks"]["rolling_24h_window_observed_across_full_run"] is True
    assert report["checks"]["rolling_24h_membership_rollover_observed"] is True
    assert report["rolling_24h_capacity"]["semantics"] == "rolling_previous_24_hours"
    assert report["rolling_24h_capacity"]["aged_out_member_application_ids"] == [1, 2, 3]
    # The campaign may remain over the cap because no-submit shadow rows count in the
    # production database. Rollover, not an artificial threshold crossing, is the gate.
    assert report["rolling_24h_capacity"]["threshold_crossed"] is False


def test_day38_policy_report_rejects_authoritative_or_missing_diagnostics():
    unsafe = _diagnostic(
        active=True,
        count=5,
        observed_at="2026-09-05T01:00:00+00:00",
        members=[1, 2, 3, 4, 5],
    )
    unsafe["authoritative"] = True
    report = _policy_transition_report(
        [
            _cycle(
                1,
                _diagnostic(
                    active=False,
                    count=5,
                    observed_at="2026-09-04T12:00:00+00:00",
                    members=[1, 2, 3, 4, 5],
                ),
            ),
            _cycle(2, unsafe),
            SimpleNamespace(
                cycle_number=3,
                status="completed",
                scheduler_result={
                    "policy_profile": "shadow_test",
                    "production_limits_enforced": False,
                },
                reconciliation_snapshot={},
            ),
        ]
    )

    assert report["passed"] is False
    assert report["checks"]["every_completed_cycle_has_policy_diagnostic"] is False
    assert report["checks"]["production_diagnostic_never_authoritative"] is False
    assert report["missing_cycle_numbers"] == [3]
    assert report["authoritative_cycle_numbers"] == [2]


def test_day38_policy_report_rejects_missing_real_window_rollover():
    first = _diagnostic(
        active=False,
        count=5,
        observed_at="2026-09-04T12:00:00+00:00",
        members=[1, 2, 3, 4, 5],
    )
    last = _diagnostic(
        active=True,
        count=5,
        observed_at="2026-09-05T11:30:00+00:00",
        members=[1, 2, 3, 4, 5],
    )
    report = _policy_transition_report([_cycle(1, first), _cycle(2, last)])

    assert report["passed"] is False
    assert report["checks"]["rolling_24h_window_observed_across_full_run"] is True
    assert report["checks"]["rolling_24h_membership_rollover_observed"] is False


def test_day38_policy_report_rejects_production_profile_as_execution_authority():
    cycle = _cycle(
        1,
        _diagnostic(
            active=False,
            count=4,
            observed_at="2026-09-04T12:00:00+00:00",
            members=[1, 2, 3, 4],
        ),
    )
    cycle.scheduler_result = {
        "policy_profile": "production",
        "production_limits_enforced": True,
    }
    report = _policy_transition_report([cycle])

    assert report["passed"] is False
    assert report["checks"]["shadow_execution_profile_remained_shadow_test"] is False
