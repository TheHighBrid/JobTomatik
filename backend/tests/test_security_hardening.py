"""Regression coverage for security-sensitive configuration and account inputs."""

import pytest
from pydantic import ValidationError

from app.auth import hash_password, verify_password
from app.config import Settings
from app.schemas.user import UserCreate


def test_development_defaults_remain_available_for_local_installations():
    settings = Settings(_env_file=None)

    assert settings.app_environment == "development"
    assert settings.allow_real_application_submit is False
    assert settings.uses_placeholder_secret is True


def test_sensitive_runtime_rejects_placeholder_secret():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(
            _env_file=None,
            allow_real_application_submit=True,
            secret_key="supersecretkey-change-in-production",
        )


def test_production_accepts_a_non_placeholder_secret():
    settings = Settings(
        _env_file=None,
        app_environment="production",
        secret_key="b1f8a9d2047e49f0b7a6dce98aa42187",
    )

    assert settings.is_production is True
    assert settings.uses_placeholder_secret is False


def test_credentialed_cors_rejects_wildcard_origin():
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        Settings(_env_file=None, cors_origins="*")


def test_account_password_policy_matches_bcrypt_byte_limit():
    user = UserCreate(email="person@example.com", password="correct horse battery staple")
    generated = hash_password(user.password)

    assert verify_password(user.password, generated) is True

    with pytest.raises(ValidationError, match="at least 8 characters"):
        UserCreate(email="person@example.com", password="short")

    with pytest.raises(ValidationError, match="72 UTF-8 bytes"):
        UserCreate(email="person@example.com", password="é" * 40)


def test_invalid_or_oversized_passwords_do_not_crash_verification():
    generated = hash_password("valid-password")

    assert verify_password("é" * 40, generated) is False
    assert verify_password("valid-password", "not-a-bcrypt-hash") is False
