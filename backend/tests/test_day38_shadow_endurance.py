from __future__ import annotations

from types import SimpleNamespace

from app.services.day38_runtime import (
    DAY38_POLICY_SNAPSHOT_KEY,
    DAY38_POLICY_TELEMETRY_VERSION,
)
from app.services.day38_shadow_endurance import _policy_transition_report


def _diagnostic(*, active: bool, count: int, cap: int = 5) -> dict:
    return {
        "version": DAY38_POLICY_TELEMETRY_VERSION,
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


def test_day38_policy_report_requires_real_quiet_and_capacity_transitions():
    report = _policy_transition_report(
        [
            _cycle(1, _diagnostic(active=False, count=4)),
            _cycle(2, _diagnostic(active=True, count=5)),
            _cycle(3, _diagnostic(active=False, count=6)),
        ]
    )

    assert report["passed"] is True
    assert report["checks"]["quiet_hours_transition_observed"] is True
    assert report["checks"]["rolling_24h_capacity_threshold_crossed"] is True
    assert report["rolling_24h_capacity"]["semantics"] == "rolling_previous_24_hours"
    assert report["rolling_24h_capacity"]["minimum_count"] == 4
    assert report["rolling_24h_capacity"]["maximum_count"] == 6


def test_day38_policy_report_rejects_authoritative_or_missing_diagnostics():
    unsafe = _diagnostic(active=True, count=5)
    unsafe["authoritative"] = True
    report = _policy_transition_report(
        [
            _cycle(1, _diagnostic(active=False, count=4)),
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


def test_day38_policy_report_rejects_production_profile_as_execution_authority():
    cycle = _cycle(1, _diagnostic(active=False, count=4))
    cycle.scheduler_result = {
        "policy_profile": "production",
        "production_limits_enforced": True,
    }
    report = _policy_transition_report([cycle])

    assert report["passed"] is False
    assert report["checks"]["shadow_execution_profile_remained_shadow_test"] is False
