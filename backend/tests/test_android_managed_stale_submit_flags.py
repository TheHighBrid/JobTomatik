from __future__ import annotations

import pytest

import app.config as config_module
from app.config import Settings
from app.services import supervised_runtime_mode
from scripts import android_runtime_acceptance


def _configured_settings(*, greenhouse: bool, lever: bool, submit: bool = True) -> Settings:
    return Settings(
        _env_file=None,
        secret_key="s" * 48,
        allow_real_application_submit=submit,
        lever_supervised_pilot_enabled=lever,
        allow_real_followup_send=False,
        greenhouse_supervised_pilot_enabled=greenhouse,
    )


def test_android_managed_runtime_respects_explicit_global_and_lever_flags(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_ROLE", raising=False)

    settings = _configured_settings(greenhouse=False, lever=True)

    assert settings.allow_real_application_submit is True
    assert settings.lever_supervised_pilot_enabled is True
    assert android_runtime_acceptance._configured_acceptance_profile(settings) == "supervised_lever"


def test_android_managed_greenhouse_only_configuration_preserves_existing_pilot(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_ROLE", raising=False)

    settings = _configured_settings(greenhouse=True, lever=False)

    assert settings.allow_real_application_submit is True
    assert settings.greenhouse_supervised_pilot_enabled is True
    assert settings.lever_supervised_pilot_enabled is False
    assert android_runtime_acceptance._configured_acceptance_profile(settings) == "supervised_greenhouse"


def test_android_managed_dual_pilot_configuration_is_rejected(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_ROLE", raising=False)

    settings = _configured_settings(greenhouse=True, lever=True)

    assert settings.allow_real_application_submit is True
    assert settings.lever_supervised_pilot_enabled is True
    with pytest.raises(RuntimeError, match="exactly one ATS pilot switch"):
        android_runtime_acceptance._configured_acceptance_profile(settings)


def test_android_managed_api_respects_explicit_lever_pilot_without_lease(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "api")
    monkeypatch.setattr(config_module, "_supervised_submission_service_on_stack", lambda: False)
    monkeypatch.setattr(
        supervised_runtime_mode,
        "lever_supervised_runtime_lease_active",
        lambda *args, **kwargs: False,
    )

    settings = _configured_settings(greenhouse=False, lever=True)
    assert settings.allow_real_application_submit is True
    assert settings.lever_supervised_pilot_enabled is True


def test_shadow_acceptance_is_blocked_while_active_lever_lease_exists(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.setattr(
        android_runtime_acceptance,
        "runtime_lease_status",
        lambda *_args, **_kwargs: {"active": True},
    )

    with pytest.raises(RuntimeError, match="shadow runtime acceptance is blocked"):
        android_runtime_acceptance.run_acceptance("shadow_no_submit")


def test_non_android_runtime_preserves_explicit_configuration(monkeypatch):
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_MODE", raising=False)
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_ROLE", raising=False)

    settings = _configured_settings(greenhouse=False, lever=True)

    assert settings.allow_real_application_submit is True
    assert settings.lever_supervised_pilot_enabled is True
