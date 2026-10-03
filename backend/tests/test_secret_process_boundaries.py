"""Synthetic independent-process checks for signing and durable secret roots."""

import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.config import DEFAULT_SECRET_KEY, PLACEHOLDER_SECRET_MARKERS, Settings, get_settings
from app.services import answer_policy, handoff_session


SENSITIVE_MODES = (
    {"app_environment": "production"},
    {"allow_real_application_submit": True},
    {"allow_real_followup_send": True},
    {"greenhouse_supervised_pilot_enabled": True},
    {"lever_supervised_pilot_enabled": True},
)


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Do not accidentally inherit a runner's safe key or sensitive flags."""
    for name in (
        "SECRET_KEY", "ANSWER_VAULT_KEY", "APP_ENV", "APP_ENVIRONMENT",
        "ALLOW_REAL_APPLICATION_SUBMIT", "ALLOW_REAL_FOLLOWUP_SEND",
        "GREENHOUSE_SUPERVISED_PILOT_ENABLED", "LEVER_SUPERVISED_PILOT_ENABLED",
        "JOBTOMATIK_RUNTIME_MODE", "JOBTOMATIK_RUNTIME_ROLE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("mode", SENSITIVE_MODES)
def test_each_sensitive_mode_rejects_process_fallback(isolated_config, mode):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, **mode)


@pytest.mark.parametrize("mode", SENSITIVE_MODES)
@pytest.mark.parametrize("marker", PLACEHOLDER_SECRET_MARKERS)
def test_each_sensitive_mode_rejects_explicit_historical_markers(isolated_config, mode, marker):
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None, secret_key=marker.upper() + secrets.token_urlsafe(48), **mode)


@pytest.mark.parametrize("mode", SENSITIVE_MODES)
def test_each_sensitive_mode_accepts_an_explicit_random_key(isolated_config, mode):
    settings = Settings(_env_file=None, secret_key=secrets.token_urlsafe(48), **mode)
    assert not settings.uses_placeholder_secret


@pytest.mark.parametrize("operation", (
    answer_policy.encrypt_policy_value,
    handoff_session.encrypt_handoff_secret,
    handoff_session._secret_hash,
))
def test_ephemeral_key_cannot_create_durable_crypto(isolated_config, operation):
    with pytest.raises(ValueError, match="stable secret"):
        operation("synthetic-value")


def test_explicit_vault_key_does_not_authorize_ephemeral_handoff_hash(isolated_config, monkeypatch):
    monkeypatch.setenv("ANSWER_VAULT_KEY", secrets.token_urlsafe(48))
    encrypted = answer_policy.encrypt_policy_value("synthetic-answer")
    assert answer_policy.decrypt_policy_value(encrypted) == "synthetic-answer"
    with pytest.raises(ValueError, match="SECRET_KEY"):
        handoff_session._secret_hash("synthetic-token")


def test_cache_clear_does_not_turn_fallback_into_configured_secret(isolated_config):
    first = get_settings()
    get_settings.cache_clear()
    second = get_settings()
    assert first is not second
    assert first.secret_key == second.secret_key == DEFAULT_SECRET_KEY
    assert first.uses_placeholder_secret and second.uses_placeholder_secret


def _interpreter(code, env, cwd):
    return json.loads(subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=cwd,
        capture_output=True, text=True, check=True, timeout=20,
    ).stdout)


def test_independent_interpreters_share_configured_crypto_but_not_fallback(isolated_config, tmp_path):
    backend = str(Path(__file__).resolve().parents[1])
    env = dict(os.environ, PYTHONPATH=backend)
    fallback_code = (
        "import hashlib,json; from app.config import Settings; s=Settings(_env_file=None); "
        "print(json.dumps({'digest':hashlib.sha256(s.secret_key.encode()).hexdigest(),"
        "'placeholder':s.uses_placeholder_secret}))"
    )
    first = _interpreter(fallback_code, env, tmp_path)
    second = _interpreter(fallback_code, env, tmp_path)
    assert first["digest"] != second["digest"]
    assert first["placeholder"] and second["placeholder"]

    env["SECRET_KEY"] = secrets.token_urlsafe(48)
    create = (
        "import json; from app.services.answer_policy import encrypt_policy_value; "
        "from app.services.handoff_session import encrypt_handoff_secret,_secret_hash; "
        "print(json.dumps({'policy':encrypt_policy_value('synthetic-answer'),"
        "'handoff':encrypt_handoff_secret('synthetic-token'),'hash':_secret_hash('synthetic-token')}))"
    )
    created = _interpreter(create, env, tmp_path)
    env["SYNTHETIC_CRYPTO"] = json.dumps(created)
    read = (
        "import json,os; from app.services.answer_policy import decrypt_policy_value; "
        "from app.services.handoff_session import decrypt_handoff_secret,_secret_hash; "
        "c=json.loads(os.environ['SYNTHETIC_CRYPTO']); print(json.dumps({"
        "'policy':decrypt_policy_value(c['policy']),'handoff':decrypt_handoff_secret(c['handoff']),"
        "'hash_matches':_secret_hash('synthetic-token')==c['hash']}))"
    )
    recovered = _interpreter(read, env, tmp_path)
    assert recovered == {
        "policy": "synthetic-answer", "handoff": "synthetic-token", "hash_matches": True,
    }
