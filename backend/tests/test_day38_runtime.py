from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.services import day38_runtime
from app.services.operations_policy import AutomationDecision


class _Query:
    def __init__(self, *, rows=None, scalar_value=None):
        self._rows = list(rows or [])
        self._scalar_value = scalar_value

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)

    def scalar(self):
        return self._scalar_value


class _Db:
    def __init__(self):
        self.calls = 0

    def query(self, *_args):
        self.calls += 1
        if self.calls == 1:
            return _Query(
                rows=[
                    (41, datetime(2026, 9, 4, 9, 0, 0)),
                    (42, datetime(2026, 9, 4, 11, 30, 0)),
                ]
            )
        return _Query(scalar_value=7)


def test_day38_production_policy_diagnostic_is_non_authoritative_and_tracks_members(monkeypatch):
    monkeypatch.setattr(
        day38_runtime,
        "get_operations_settings",
        lambda: SimpleNamespace(
            default_daily_cap=5,
            default_weekly_cap=20,
            quiet_hours_start_utc=0,
            quiet_hours_end_utc=6,
        ),
    )
    monkeypatch.setattr(
        day38_runtime,
        "evaluate_autopilot_policy",
        lambda *_args, **_kwargs: AutomationDecision(
            False,
            "quiet_hours",
            "production would pause",
            {"remaining_daily": 3, "remaining_weekly": 13},
        ),
    )
    user = SimpleNamespace(
        id=7,
        automation_settings={
            "auto_apply_daily_limit": 5,
            "auto_apply_weekly_limit": 20,
            "quiet_hours_start_utc": 0,
            "quiet_hours_end_utc": 6,
        },
    )

    result = day38_runtime.production_policy_diagnostic(
        _Db(),
        user,
        now=datetime(2026, 9, 5, 1, 0, 0),
    )

    assert result["authoritative"] is False
    assert result["execution_policy_profile"] == "shadow_test"
    assert result["diagnostic_policy_profile"] == "production"
    assert result["production_decision"]["code"] == "quiet_hours"
    assert result["quiet_hours"]["active"] is True
    assert result["rolling_24h_capacity"]["semantics"] == "rolling_previous_24_hours"
    assert result["rolling_24h_capacity"]["member_application_ids"] == [41, 42]
    assert result["rolling_24h_capacity"]["count"] == 2
    assert result["rolling_24h_capacity"]["cap"] == 5
    assert result["rolling_24h_capacity"]["remaining"] == 3
    assert result["rolling_7d_capacity"]["count"] == 7
    assert result["safety"] == {
        "used_to_authorize_shadow_execution": False,
        "used_to_block_shadow_execution": False,
        "submission_authorized": False,
        "outreach_authorized": False,
    }
