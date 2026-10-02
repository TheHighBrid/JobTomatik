from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.services import supervised_runtime_mode
from app.services.operator_assisted_context import operator_final_action_scope
from app.services.operator_assisted_handoff_integration import _log_target_ref
from app.services.supervised_runtime import supervised_target_scope


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _safe_settings() -> Settings:
    return Settings(
        _env_file=None,
        secret_key="s" * 48,
        allow_real_application_submit=False,
        allow_real_followup_send=False,
        greenhouse_supervised_pilot_enabled=False,
        lever_supervised_pilot_enabled=False,
    )


def test_worker_lease_is_suppressed_only_inside_explicit_final_action_scope(
    monkeypatch,
):
    settings = _safe_settings()
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_MODE", "android_managed")
    monkeypatch.setenv("JOBTOMATIK_RUNTIME_ROLE", "worker")
    monkeypatch.setattr(
        supervised_runtime_mode,
        "lever_supervised_runtime_lease_active",
        lambda *args, **kwargs: True,
    )

    with supervised_target_scope({"platform": "lever", "posting_id": "abc"}):
        assert settings.allow_real_application_submit is True
        assert settings.lever_supervised_pilot_enabled is True

        with operator_final_action_scope():
            assert settings.allow_real_application_submit is False
            assert settings.lever_supervised_pilot_enabled is False

        assert settings.allow_real_application_submit is True
        assert settings.lever_supervised_pilot_enabled is True


def test_final_action_log_reference_drops_sensitive_url_components():
    raw = (
        "https://candidate:password@jobs.lever.co:8443/example/private-posting/apply"
        "?candidate=123&token=super-secret#session-fragment"
    )

    reference = _log_target_ref(raw)

    assert reference.startswith("https://jobs.lever.co:8443#")
    for sensitive_value in (
        "candidate:password@",
        "password",
        "private-posting",
        "candidate",
        "123",
        "super-secret",
        "session-fragment",
        "/apply",
        "?",
    ):
        assert sensitive_value not in reference


def test_android_stack_requires_exact_current_pyjwt_version():
    script = (BACKEND_ROOT / "scripts/manage_android_stack.sh").read_text(
        encoding="utf-8"
    )

    assert 'sys.exit(jwt.__version__ != "2.15.0")' in script
    assert 'assert jwt.__version__ == "2.15.0"' not in script
    assert "'PyJWT==2.15.0'" in script
    assert "'PyJWT==2.13.0'" not in script
