from types import SimpleNamespace

from app.services import operator_assisted_submission as operator_service


def _base_preflight():
    return {
        "platform": "lever",
        "blockers": [
            "global_live_submit_disabled",
            "lever_supervised_pilot_disabled",
        ],
        "global_live_submit_enabled": False,
        "platform_pilot_enabled": False,
    }


def _stub_structural_preflight(monkeypatch):
    monkeypatch.setattr(
        operator_service,
        "build_supervised_preflight",
        lambda *_args, **_kwargs: _base_preflight(),
    )
    monkeypatch.setattr(
        operator_service,
        "_active_final_submit_boundary",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        operator_service,
        "get_supervised_platform_policy",
        lambda _platform: SimpleNamespace(
            pilot_disabled_blocker="lever_supervised_pilot_disabled"
        ),
    )


def test_operator_preflight_blocks_when_canonical_operations_autopilot_is_on(monkeypatch):
    _stub_structural_preflight(monkeypatch)
    monkeypatch.setattr(
        operator_service,
        "get_operations_settings",
        lambda: SimpleNamespace(autopilot_enabled=True),
    )

    result = operator_service.build_operator_assisted_preflight(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
    )

    assert result["autopilot_enabled"] is True
    assert result["ready"] is False
    assert "operator_assisted_requires_autopilot_disabled" in result["blockers"]


def test_operator_preflight_allows_canonical_operations_autopilot_off(monkeypatch):
    _stub_structural_preflight(monkeypatch)
    monkeypatch.setattr(
        operator_service,
        "get_operations_settings",
        lambda: SimpleNamespace(autopilot_enabled=False),
    )

    result = operator_service.build_operator_assisted_preflight(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
    )

    assert result["autopilot_enabled"] is False
    assert result["ready"] is True
    assert "operator_assisted_requires_autopilot_disabled" not in result["blockers"]
