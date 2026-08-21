from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import android_runtime_acceptance as acceptance


def _settings(**overrides):
    values = {
        "allow_real_application_submit": False,
        "allow_real_followup_send": False,
        "greenhouse_supervised_pilot_enabled": False,
        "lever_supervised_pilot_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_android_acceptance_selects_shadow_profile_when_real_submit_is_disabled():
    settings = _settings()

    assert (
        acceptance._configured_acceptance_profile(settings)
        == acceptance.SHADOW_ACCEPTANCE_PROFILE
    )


def test_android_acceptance_selects_exact_greenhouse_supervised_profile():
    settings = _settings(
        allow_real_application_submit=True,
        greenhouse_supervised_pilot_enabled=True,
    )

    assert acceptance._configured_acceptance_profile(settings) == "supervised_greenhouse"


def test_android_acceptance_rejects_real_submit_without_one_exact_pilot():
    with pytest.raises(RuntimeError, match="exactly one ATS pilot switch"):
        acceptance._configured_acceptance_profile(
            _settings(allow_real_application_submit=True)
        )

    with pytest.raises(RuntimeError, match="exactly one ATS pilot switch"):
        acceptance._configured_acceptance_profile(
            _settings(
                allow_real_application_submit=True,
                greenhouse_supervised_pilot_enabled=True,
                lever_supervised_pilot_enabled=True,
            )
        )


def test_android_acceptance_rejects_followup_sending_in_any_profile():
    with pytest.raises(RuntimeError, match="follow-up sending"):
        acceptance._configured_acceptance_profile(
            _settings(allow_real_followup_send=True)
        )


def test_supervised_profile_reuses_structural_base_without_lying_in_receipt(monkeypatch):
    authoritative = _settings(
        allow_real_application_submit=True,
        greenhouse_supervised_pilot_enabled=True,
    )
    observed = {}

    monkeypatch.setattr(acceptance, "_backend_settings", lambda: authoritative)
    monkeypatch.setattr(
        acceptance,
        "_playwright_browser_acceptance",
        lambda: {
            "playwright_attach_ready": True,
            "browser_owned_by_jobtomatik": False,
        },
    )

    def fake_base_run_acceptance():
        projected = acceptance._base.get_settings()
        observed["projected"] = projected
        return {
            "browser": {},
            "safety": {
                "real_submission_disabled": True,
                "final_submit_allowed": False,
                "outreach_authorized": False,
            },
        }

    monkeypatch.setattr(acceptance._base, "run_acceptance", fake_base_run_acceptance)

    payload = acceptance.run_acceptance("supervised_greenhouse")

    projected = observed["projected"]
    assert projected is not authoritative
    assert authoritative.allow_real_application_submit is True
    assert projected.allow_real_application_submit is False
    assert projected.greenhouse_supervised_pilot_enabled is True
    assert projected.lever_supervised_pilot_enabled is False
    assert payload["acceptance_profile"] == "supervised_greenhouse"
    assert payload["safety"] == {
        "real_submission_disabled": False,
        "supervised_submission_window": True,
        "supervised_platform": "greenhouse",
        "one_time_approval_required": True,
        "final_submit_allowed": False,
        "outreach_authorized": False,
    }
    assert payload["browser"]["playwright_attach_ready"] is True


def test_supervised_profile_cannot_cross_to_another_enabled_platform(monkeypatch):
    authoritative = _settings(
        allow_real_application_submit=True,
        lever_supervised_pilot_enabled=True,
    )
    monkeypatch.setattr(acceptance, "_backend_settings", lambda: authoritative)

    with pytest.raises(RuntimeError, match="must match the only enabled ATS pilot switch"):
        acceptance.run_acceptance("supervised_greenhouse")
