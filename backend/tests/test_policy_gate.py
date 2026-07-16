from datetime import datetime, time, timedelta

from app.services.policy_gate import (
    JobContext,
    OperationCounters,
    PolicyConfig,
    PolicyGate,
)


NOW = datetime(2026, 7, 16, 12, 0, 0)


def _ctx(**overrides):
    values = {
        "adapter_platform": "greenhouse",
        "employer_id": "acme",
        "employer_name": "Acme",
        "job_id": "job-1",
        "location": "Ottawa",
        "salary_min": 80000,
        "seniority": "mid",
        "language": "english",
        "requires_sponsorship": False,
        "source": "jobbank",
    }
    values.update(overrides)
    return JobContext(**values)


def _config(**overrides):
    values = {
        "global_autonomy_enabled": True,
        "platform_enabled": {"greenhouse": True},
        "platform_maturity": {"greenhouse": "certified_autonomous"},
        "daily_cap_global": 5,
        "weekly_cap_global": 20,
        "daily_cap_per_employer": 1,
        "require_known_job_attributes": True,
    }
    values.update(overrides)
    return PolicyConfig(**values)


def _counters(**overrides):
    values = {
        "submissions_today_global": 0,
        "submissions_this_week_global": 0,
        "submissions_today_for_employer": {},
        "consecutive_failures_by_source": {},
        "circuit_open_until_by_adapter": {},
    }
    values.update(overrides)
    return OperationCounters(**values)


def test_global_switch_blocks_everything():
    result = PolicyGate(_config(global_autonomy_enabled=False)).evaluate(_ctx(), _counters())
    assert result.allowed is False
    assert result.reason_code == "global_kill_switch_off"


def test_platform_must_be_explicitly_enabled():
    result = PolicyGate(_config(platform_enabled={})).evaluate(_ctx(), _counters())
    assert result.allowed is False
    assert result.reason_code == "platform_kill_switch_off"


def test_runtime_maturity_must_be_certified_autonomous():
    result = PolicyGate(
        _config(platform_maturity={"greenhouse": "fixture_live_inspection_certified"})
    ).evaluate(_ctx(), _counters())
    assert result.allowed is False
    assert result.reason_code == "platform_not_certified"


def test_unknown_job_data_blocks_even_without_value_restrictions():
    result = PolicyGate(_config()).evaluate(_ctx(language=None), _counters())
    assert result.allowed is False
    assert result.reason_code == "job_attributes_unknown"
    assert "language" in result.detail


def test_disabling_known_attribute_requirement_does_not_disable_explicit_filters():
    result = PolicyGate(
        _config(require_known_job_attributes=False, min_salary=90000)
    ).evaluate(_ctx(salary_min=None), _counters())
    assert result.allowed is False
    assert result.reason_code == "below_min_salary"


def test_missing_attributes_may_pass_only_when_operator_explicitly_allows_it():
    result = PolicyGate(
        _config(
            require_known_job_attributes=False,
            require_sponsorship_match=False,
        )
    ).evaluate(
        _ctx(
            location=None,
            salary_min=None,
            seniority=None,
            language=None,
            requires_sponsorship=None,
        ),
        _counters(),
    )
    assert result.allowed is True


def test_wraparound_quiet_hours_block():
    gate = PolicyGate(
        _config(quiet_hours_start=time(22), quiet_hours_end=time(6)),
        now_fn=lambda: datetime(2026, 7, 16, 23, 0, 0),
    )
    result = gate.evaluate(_ctx(), _counters())
    assert result.allowed is False
    assert result.reason_code == "quiet_hours"


def test_open_circuit_blocks():
    result = PolicyGate(_config(), now_fn=lambda: NOW).evaluate(
        _ctx(),
        _counters(circuit_open_until_by_adapter={"greenhouse": NOW + timedelta(minutes=30)}),
    )
    assert result.allowed is False
    assert result.reason_code == "circuit_open"


def test_all_checks_pass():
    result = PolicyGate(_config()).evaluate(_ctx(), _counters())
    assert result.allowed is True
    assert result.reason_code == "all_checks_passed"
