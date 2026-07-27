"""Regression guard for the hard live-submission default."""


def test_real_application_submit_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_REAL_APPLICATION_SUBMIT", raising=False)

    from app.config import Settings

    assert Settings(_env_file=None).allow_real_application_submit is False


def test_allow_real_application_submit_env_override_still_works(monkeypatch):
    monkeypatch.setenv("ALLOW_REAL_APPLICATION_SUBMIT", "true")
    monkeypatch.setenv("SECRET_KEY", "f38f7c88c75441e8baf836f25f8c2f12")

    from app.config import Settings

    settings = Settings(_env_file=None)
    assert settings.allow_real_application_submit is True
    assert settings.uses_placeholder_secret is False
