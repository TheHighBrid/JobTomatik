from __future__ import annotations

import app.config as config_module
from app.config import Settings
from app.services import supervised_runtime_mode
from scripts import android_runtime_acceptance


def _configured_live_settings() -> Settings:
    return Settings(
        _env_file=None,
        secret_key="s" * 48,
        allow_real_application_submit=True,
        lever_supervised_pilot_enabled=True,
        allow_real_followup_send=False,
        greenhouse_supervised_pilot_enabled=False,
    )


def test_android_managed_runtime_ignores_stale_persisted_submit_flags(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_ROLE", raising=False)

    settings = _configured_live_settings()

    assert settings.allow_real_application_submit is False
    assert settings.lever_supervised_pilot_enabled is False
    assert android_runtime_acceptance._configured_acceptance_profile(settings) == "shadow_no_submit"


def test_android_managed_api_requires_exact_supervised_lease_scope(monkeypatch):
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "api")
    monkeypatch.setattr(config_module, "_supervised_submission_service_on_stack", lambda: False)
    monkeypatch.setattr(
        supervised_runtime_mode,
        "lever_supervised_runtime_lease_active",
        lambda *args, **kwargs: True,
    )

    settings = _configured_live_settings()
    assert settings.allow_real_application_submit is False
    assert settings.lever_supervised_pilot_enabled is False

    monkeypatch.setattr(config_module, "_supervised_submission_service_on_stack", lambda: True)
    assert settings.allow_real_application_submit is True
    assert settings.lever_supervised_pilot_enabled is True


def test_non_android_runtime_preserves_explicit_configuration(monkeypatch):
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_MODE", raising=False)
    monkeypatch.delenv("JOBTOMATIK_RUNTIME_ROLE", raising=False)

    settings = _configured_live_settings()

    assert settings.allow_real_application_submit is True
    assert settings.lever_supervised_pilot_enabled is True
