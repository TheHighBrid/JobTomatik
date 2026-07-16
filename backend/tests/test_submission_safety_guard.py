"""Regression guard for the hard live-submission default."""


def test_real_application_submit_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_REAL_APPLICATION_SUBMIT", raising=False)

    from app.config import Settings

    assert Settings(_env_file=None).allow_real_application_submit is False


def test_allow_real_application_submit_env_override_still_works(monkeypatch):
    monkeypatch.setenv("ALLOW_REAL_APPLICATION_SUBMIT", "true")

    from app.config import Settings

    assert Settings(_env_file=None).allow_real_application_submit is True
